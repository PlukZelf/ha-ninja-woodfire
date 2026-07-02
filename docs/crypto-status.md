# BLE Crypto — Reverse Engineering Status

_Last updated: 2026-07-02_

This document records what is known about the encryption used on the
Ninja Woodfire Pro BLE link (advertisements and GATT), based on static
analysis of `libgrillcore_android.so` plus targeted dynamic verification.

> Supersedes an earlier version of this document from 2026-06-28, which was
> based on a **different app build** (different function offsets, e.g.
> `extDecryptData` at `0x142560` there vs `0x10401c` in the build analyzed
> below) — always confirm the binary in hand matches the currently installed
> app (pull it fresh via `adb`, verify with `tools/elf_symbols.py`) before
> reusing recorded offsets.

## Binary under analysis

Pulled directly from the installed app on device (`adb pull` on the `pm
path` result), NOT reused from an older capture — this matters, see the
warning above.

| Property | Value |
| --- | --- |
| File | `libgrillcore_android.so` |
| Arch | ELF64 AArch64 |
| Size | 4,678,184 bytes |
| Verified via | `tools/elf_symbols.py` `.dynsym` parse — `extProcessBTData` vaddr `0x10ae40` matches live Frida-captured runtime offset exactly |

## Two separate crypto surfaces: adverts vs GATT

The BLE advertisement channel and the post-`Connect` GATT channel use
**unrelated crypto**, both AES-based, with different (and differently
solved) key situations:

| | Advertisements | GATT (post-Connect) |
| --- | --- | --- |
| Key | **Static**, embedded as constants in the `.so` | **Per-session**, negotiated fresh on every `Connect`, held only in-memory (not persisted to disk on either side) |
| Status | ✅ Fully decoded (see below) | ❌ Unsolved — out of scope for a read-only integration |
| Needed for | Passive state reading (temps, probe, mode) | Sending commands (set temp, start cook) |

## Advertisement decoding — SOLVED

### Call chain

```
extProcessBTData (0x10ae40)
  -> grill registry lookup (matches by MAC/UUID)
  -> FUN_00230460           ; whitening + AES-256 transform (per AD-structure half)
  -> FUN_0022f11c           ; "parse_grill_and_probe_status" — plain bit-field parser
       -> FUN_0023085c      ; LSB-first bitstream reader (NOT crypto)
```

`FUN_00230460` is the actual crypto step. It is **not** a simple stream
cipher: it applies a position-dependent add+XOR whitening pass (seeded by a
checksum over the input, static constant tables baked into the `.so`) and
then calls `FUN_00231934`, which is a real **fixslice AES-256** core (the
same optimized bitsliced implementation used by the Rust `aes` crate,
confirmed by matching round-function structure against
`aes-0.8.4/src/soft/fixslice64.rs`).

**Important calling-convention detail:** `FUN_00230460` must be called ONCE
PER RAW AD-STRUCTURE PAYLOAD HALF (a 20-byte and a 23-byte manufacturer-data
payload, at offsets `0xb` and `0x27` of the raw ~62-byte advert), not on the
43-byte concatenated buffer — it validates the input length is in range
`0x11..0x1f` (17-31 decimal) and returns an error sentinel outside that
range.

### Verification

Decoded a real captured advertisement (company ID `0x0C4F`) and confirmed
correctness two independent ways:

1. The decoded buffer's byte `0x13` = `0x34` (ASCII `'4'`) and last byte =
   `0x21` (ASCII `'!'`) — exactly the two sanity-check markers the real
   parser (`FUN_0022f11c`) itself validates before trusting the buffer.
2. Bytes 20-25 of the decoded buffer are the grill's real MAC address, in
   the clear (not reproduced here — never commit real device MAC addresses,
   see `CLAUDE.md`). Independently re-derived via a from-scratch Python port
   of the bit-field reader (`tools/decode_advert_fields.py`) applied to the
   same decoded bytes — two unrelated code paths landing on the identical
   MAC address is strong confirmation the whole pipeline is correct.

### Full bit-field layout (344 bits = 43 bytes, zero slack)

Field read order (not a flat table — the real control flow reuses width
groups):

1. **21 header fields**, widths (bits) `8,8,5,4,5,7,1,2,7,1,1,1,1,17,10,10,10,6,16,8,32` (160 bits).
2. **6× 8-bit fields** — the device's MAC address (48 bits).
3. **1× 8-bit field** — one more byte immediately after the MAC (semantics unknown).
4. **2× probe blocks**, each 9 fields with widths `3,1,1,3,4,4,5,10,17` (48 bits/probe,
   96 bits total) — matches the two physical probes (`probe1`/`probe2`) documented
   in `CLAUDE.md`.
5. **1 final 32-bit field.**

Total: 160 + 48 + 8 + 96 + 32 = 344 bits, exactly 43 bytes — a strong
structural check that this decomposition is correct (an earlier, wrong
transcription of this table also happened to sum to 344 bits by
coincidence of the same numbers in the wrong grouping; this version is
verified against the actual decompiled control flow, not just a bit-count
coincidence).

Field **semantics** (which field is target temp, current temp, cook mode,
etc.) are being mapped via live captures correlated against known grill/app
state changes (idle vs cooking, probe states, etc.) — see
`tools/live_decode.py`, a continuous passive BLE scanner (no phone/app
needed) that decodes and prints each new state in real time for this
purpose.

### Header field mapping (confirmed so far, HEADER_WIDTHS indices)

Confirmed by correlating live captures against a real cook session (target
temp changed from 40 to 45 in the app while `tools/live_decode.py` was
running):

| Index | Meaning | Evidence |
| --- | --- | --- |
| 13 | Cook time **remaining**, in seconds | Counted down steadily in real time (e.g. 21513 -> 21469 over 44 real-world seconds); cross-checked against the app's displayed remaining time (~5h56m) at `21600 - elapsed = 21469` (5h57m49s) — within ~2 min, consistent with the app rounding its display to whole minutes. |
| 14 | Live temperature reading (probably grill/oven temp) | Small continuous fluctuation (91-96) consistent with real sensor noise, unlike the fixed setpoint fields. |
| 15 | **Probe 1 live temperature**, whole degrees Celsius (no scaling) | Constant `18` for the entire session while the probe sat at room temp (matched the user's own app reading of "18°C"). Confirmed dynamically: rose to `25` then settled `24`, `23` when the user held the probe tip in their palm, tracking real-world hand-contact warming/cooling exactly. **Not** in the `probes[]` sub-block — despite being physically a probe reading, it's encoded directly in the header. |
| 18 | Cook time **set/total**, in seconds | Constant `21600` (= 6h00m) throughout the whole session — matches `field[13]` counting down from it. |
| 19 | **Target/set temperature**, whole degrees (no scaling) | Flipped from `40` to `45` at the exact moment the user changed the app's target temp from 40°C to 45°C. |

**Cook mode — field 3 (revised, second correction):** an earlier version of
this doc guessed field 2, then briefly fields 3+4 jointly. A third real mode
change (Dehydrate -> Smoke @ 120°C/2h04m -> Grill w/ probe1 target 75°C)
resolves it: field 3 alone matches `CLAUDE.md`'s documented `cookMode` enum
order (`NotSet, Grill, AirCrisp, Roast, Bake, Broil, Smoke, Dehydrate,
MaxRoast, SlowCook`) on BOTH confirmed endpoints — `7` during Dehydrate
(index 7) and `1` during Grill (index 1). The one earlier "Smoke=`2`"
reading doesn't fit this enum (Smoke would be index 6) and is most likely a
transient mid-navigation UI state captured while the user was still
scrolling the app's mode picker, not committed Smoke mode. Field 2 stayed
constant at `7` across every mode tested so far (Dehydrate, Smoke-setup,
Grill) — clearly NOT mode-related, real meaning still unknown. Field 4 and
field 6 also still unconfirmed.

**Fields 7 and 9 — new observation, cookType-related (tentative).** Comparing
the same live capture: during Dehydrate/Smoke (both plain timed cooks, no
probe target), `header[7]=0` and `header[9]=0`. Once switched to Grill with
a probe1 target of 75°C, both flipped to `header[7]=1` and `header[9]=1`.
Plausible reading: one or both encode **cookType** (Timed vs Probe) at the
header level, separate from the per-probe `probes[2]`/`probes[4]` flags
noted below — but since both fields changed together in this single test,
they aren't yet independently distinguished from each other. Needs a
Timed-cook-without-probe-target vs. Probe-cook contrast on a mode that isn't
also a mode change (to rule out mode-correlation instead of cookType).

**Probe fields — now well understood.** Tested with a probe-target cook
(Grill, probe1 target 75°C): `probes[0]` went from the idle baseline
`[0,1,0,0,0,0,0,0,0]` to `[0,1,1,0,1,0,0,75,0]`. This gives:

| `probes[]` index | Meaning | Evidence |
| --- | --- | --- |
| 1 | Probe **plugged in** flag | Constant `1` all session (user confirmed probe physically connected throughout) — not yet contrast-tested against physically unplugging it. |
| 2 | Probe **target-temp-is-set** flag (or "probe cook active") | `0` during plain timed cooks (Dehydrate/Smoke, no probe target set), `1` once a probe target temp was configured (Grill w/ 75°C target). |
| 4 | Related active/armed flag (co-varies with index 2) | Same `0`->`1` transition as index 2 in this test — not yet independently distinguished; could be a second bit of the same conceptual state (e.g. "target set" vs "actively tracking toward target"). |
| 7 (10-bit field) | Probe **target temperature**, whole degrees Celsius | Exactly `75` — matches the user's set probe1 target of 75°C precisely. |

Index 15's earlier finding (probe1's *live/current* temperature reading
lives in the **header**, not in `probes[]`) still stands — `probes[]`
appears to be specifically about the *target*/armed state, while current
readings are reported via the header fields instead.

**Preheat-related fields — partially observed, not yet nailed down.**
During Grill-mode preheating (before pressing "skip preheating" at ~1%
progress): `header[13]=600`, `header[18]=100`. Immediately after skipping:
`header[13]=60`, `header[18]=23`, `header[17]` flipped `0`->`1`. Plausible
reading: `header[18]` may be a preheat-related estimate/progress value (100
-> lower after skip) and `header[17]` an "actively cooking"/"preheat
skipped" flag, but this needs a CLEAN preheat-to-completion observation
(0% -> 100% without skipping) to confirm rather than guess from a single
skip event. `header[19]` read `8` during this Grill+probe session, NOT a
literal oven temperature — the app only showed a qualitative "grill temp
hoog" (high) setting here, no explicit numeric target, suggesting
`header[19]` may encode a **heat-level preset** (e.g. 1-10 scale) rather
than literal degrees when no explicit numeric grill temperature is set —
context-dependent on cook type, needs more testing to confirm.

Still unmapped: the `extra_byte` after the MAC, and the final 32-bit field
(changes every single advertisement, even with the same header — likely a
rolling counter, sequence number, or short-term nonce/checksum, not
app-visible state).

## GATT session key — unsolved, lower priority

`extSendBTPayload {"cmd":"Connect"}` triggers a fresh handshake; the
resulting session key lives only in the library's internal Rust state,
never persisted to disk on the phone (confirmed via full filesystem +
MMKV-store dump — see repo history for `frida_dump_storage.js` /
`frida_mmkv_key.js` findings). Decrypting/encrypting GATT indications
(`extDecryptData`/`extEncryptData`) only works after a live `Connect`
handshake for that specific session.

**Confirmed NOT a cloud dependency either:** blocking the backend
(`ads-eu.aylanetworks.com`, this product's white-label IoT cloud vendor —
see "Cloud architecture" below) via DNS makes the official app refuse to
even attempt BLE (zero native BLE calls fire), but this is an app-side
business-logic gate, not a requirement of the grill's protocol — the app
simply chooses not to try without cloud reachability. A from-scratch
integration is not bound by that choice.

Out of scope for a read-only passive-monitoring integration (which only
needs the advert channel, now solved). Would need to be solved separately
to support sending commands (temperature changes, starting a cook, etc.).

## Cloud architecture (context only, not a shortcut)

The grill is registered on **Ayla Networks'** white-label IoT cloud
(`ads-eu.aylanetworks.com`, model `AY008MVL1`), alongside standard Auth0
OAuth for the user account. This explains the mandatory account creation,
but is **not** a shortcut for the local crypto: Ayla's own documented BLE
stack (`AylaBLEDevice`, a fixed "Ayla GATT Service" with characteristics
like `GATT_CHAR_DUID`) does not match what this grill actually exposes
(service `0000fcbb`, custom `extProcessBTData`/`extDecryptData` native
functions) — SharkNinja built its own local BLE transport+crypto on top of
Ayla's cloud backend, not Ayla's mobile BLE SDK.

## Pure-Python port — DONE (2026-07-02)

Full pure-Python port of the advert-half decryption is complete and
verified byte-for-byte against the real native code. Implementation:
`tools/advert_crypto_port.py` (`decode_advert_half(raw: bytes) -> bytes`,
uses only `pycryptodome`, no `.so`/emulator needed at runtime).

### What the earlier (2026-07-01) attempt got wrong

The previous pass correctly identified that `FUN_00230460` calls into
`FUN_002309ac`, which builds a table of 6 "rows" (each an AES-256
key + 128-bit IV pair) via a checksum + whitening pass over the raw
input, feeding a **fixslice AES-256 core** (`FUN_00231934`, confirmed
by matching `FUN_00213f44`'s round function and `FUN_00214724`'s
bit-permutation structure against RustCrypto's `aes` crate
`fixslice64.rs`). That part of the trace was correct. What it got
wrong: it assumed this whitened/derived row material was *itself*
used as the key for decrypting the actual advert bytes. It is not —
those 6 rows only exist to prepare **encrypted constants
(`__ptr_02`/`__ptr_03`) that get thrown away**; row 0 of that table
(and, separately, row 5) are just the literal static constants
`__ptr_00`/`__ptr_01`, unmodified. The advert bytes themselves are
decrypted using **row 0 directly** (i.e. the static constants), via a
*different* function, `FUN_002315a0` — not `FUN_00231934` at all, and
not any input-derived key.

This was discovered by instrumenting the Unicorn emulator with code
hooks at `FUN_00231934`'s and `FUN_002315a0`'s entry points and
dumping their actual x0-x3 argument slices for a real
`_decode_advert_half()` call: `FUN_00231934` is called only from
inside `FUN_002309ac` (10 times, always with `__ptr_02`/`__ptr_03` as
the "plaintext" argument — dead-end busywork for this codepath), while
`FUN_002315a0` is called exactly twice per advert half, always with
the *same static* 32-byte key and 16-byte IV.

### The verified algorithm

Static constants (32-byte AES-256 key, 16-byte IV), recovered from the
row-0 literal assignments in `FUN_002309ac`
(`tools/artifacts/ghidra_decompiled_rebuild.txt` lines ~681-684 and
697-698) and cross-checked byte-for-byte via direct emulator calls
into `FUN_002315a0`:

```
KEY_CONST = eb08bb107cb293618536fd3dee1d2f6cdbc3d888bfac8f53839704220f1f197e   # 32 bytes
IV_CONST  = 539ca281078468fd901e591ae1be425b                                   # 16 bytes
```

(Note: an earlier draft of this doc/`tools/advert_crypto_port.py` had
both constants **truncated by exactly one trailing byte** — a
copy-paste artifact — which is why the "block 0" hypothesis back then
only matched the first 4 output bytes of each vector: a 31-byte key
still produces *some* AES output, just wrong beyond the point the
missing key byte starts to matter in the key schedule. Always verify
these by re-reading the qword literals from the decompile directly,
not by trusting a previously-recorded hex string.)

For a raw advert half `raw` of length `n` (17-31 bytes, i.e. one
16-byte block + a 1-15 byte tail):

1. `out0 = AES-256-CBC-Decrypt(KEY_CONST, IV_CONST, raw[0:16])` — a
   single 16-byte block, so equivalent to
   `AES-256-ECB-Decrypt(KEY_CONST, raw[0:16]) XOR IV_CONST`.
2. `tail_len = n - 16` (1-15).
3. Build a second 16-byte block: `window = out0[tail_len:16] +
   raw[16:n]` — the last `16 - tail_len` bytes of `out0`, followed by
   all `tail_len` raw tail bytes.
4. `out1 = AES-256-CBC-Decrypt(KEY_CONST, IV_CONST, window)` — same
   fixed key/IV, a **fresh** single-block decrypt (not chained from
   step 1's output as an IV — both calls independently use the same
   static `IV_CONST`).
5. Final output = `out0[0:tail_len] + out1` — exactly
   `tail_len + 16 == n` bytes.

Both AES calls share the identical static key/IV — there is no
per-message or input-derived key material anywhere in this path. The
two-call "telescoping" structure exists purely because the underlying
cipher only natively processes 16-byte blocks, but the real
manufacturer-data payload lengths (20 and 23 bytes observed in
practice) aren't block-aligned; the tail gets folded into a second
block built from the otherwise-unused tail of the first block's
decrypted output.

### Verification

- All 7 hand-recorded test vectors (4× 20-byte, 3× 23-byte) match
  exactly.
- An additional 150 randomly generated vectors, covering every valid
  length from 17 to 31 bytes (10 trials each), all match exactly
  against the real native implementation (verified live via
  `tools/grillcore_emu.py` calling `FUN_00230460` directly as the
  oracle).
- `tools/advert_crypto_port.py`'s embedded `__main__` self-test
  reproduces the 7 core vectors with **no dependency on the `.so` or
  the emulator** — safe to ship to end users as the production decode
  path.

### Still open (minor, non-blocking)

- The exact bit-level reason `FUN_00231934`'s row-building machinery
  exists at all (it's computed but never consulted for anything that
  affects the final advert output) isn't understood — possibly dead
  code left over from a more general internal crypto abstraction
  shared with the (still-unsolved) GATT session-key path, or possibly
  it *is* consulted somewhere for a code path not exercised by
  advert decoding specifically (e.g. GATT). Not required to finish
  the advert port; noted here only for completeness in case it's ever
  relevant to the separate GATT session-key investigation.

## Distribution: emulator is a dev tool only, NOT shipped

`tools/grillcore_emu.py` is a Unicorn AArch64 emulator that loads the real
`.so` and can call its internal functions directly (`decode_advert()`,
`encrypt_data()`, `decrypt_data()`, etc.) — extremely useful for verifying
reverse-engineering work quickly and correctly, since it runs the *actual*
Rust/AES code instead of a hand-ported reimplementation.

**However, per `CLAUDE.md`, `libgrillcore_android.so` may never be
committed and cannot be redistributed to end users.** The emulator was
used as a **reverse-engineering oracle only**, to verify the
from-scratch pure-Python port of the advert crypto
(`tools/advert_crypto_port.py`, see above — now DONE and verified)
byte-for-byte; only that pure-Python module should be wired into
`custom_components/ninja_woodfire/` — never the emulator or the `.so`
itself.

## Tooling

All RE tooling lives in `tools/`:

- `elf_analyze.py`, `elf_symbols.py`, `disasm_func.py` — static ELF/capstone analysis.
- `grillcore_emu.py` — Unicorn AArch64 emulator (dev-only oracle, see above).
- `decode_advert_fields.py` — pure-Python bit-field reader + verified width table.
- `verify_decode_advert.py` — end-to-end regression test against a known-good sample.
- `frida_*.js` + `frida_run.py` — live device hooks (native-level; this app's Gadget
  build blocks the Java bridge, so hooks must attach directly to native exports,
  see comments in `frida_hook_btmanager.js` / `frida_ssl_native_dump.js`).
- `ghidra_decompile_*.py` — Ghidra headless post-scripts (Jython, run via
  `analyzeHeadless -postScript`).

Your own extracted `.so` goes in `tools/artifacts/extracted/lib/arm64-v8a/`
(gitignored, never committed).
