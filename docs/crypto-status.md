# BLE Crypto — Reverse Engineering Status

_Last updated: 2026-07-01_

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

## Pure-Python port attempt (2026-07-01) — harder than expected, PAUSED

Tried to replace the emulator-driven `FUN_00230460` call with a pure-Python
port, to remove the proprietary-binary dependency for end users. Black-box
probing (flipping single input bytes and observing which output bytes
change) confirmed genuine block-cipher-like full diffusion — consistent
with real AES — but a first hypothesis ("`output[0:16]` is plain
AES-256-ECB with the static 32-byte key found in `__ptr_02`") **failed**:
neither encrypt nor decrypt with that key matched the emulator's output.

Re-reading the decompile (`tools/artifacts/ghidra_decompiled_rebuild.txt`,
`FUN_002309ac`) shows why: the AES-256 core (`FUN_00231934`) is NOT called
with the static `__ptr_02` constant as its key argument. It's called with a
**whitened copy of `__ptr_00`** (a different 32-byte constant, first
XOR/add-mixed with the raw input bytes) as the key-schedule input, and a
similarly whitened copy of `__ptr_01` as the initial block/state. The static
`__ptr_02`/`__ptr_03` constants are only used in a **second**, separate call
to `FUN_00231934` per row, as additional mixing material — not as the
primary key.

**Conclusion: the key material itself is derived from the input, not just
static.** This is a materially harder porting job than "AES with a fixed
key" — a correct pure-Python port needs the FULL whitening/checksum chain
traced faithfully (checksum formula over cycled input bytes, the
per-position `cVar6` additive term, exactly which buffer feeds which
`FUN_00231934` argument slot), not a shortcut through a standard crypto
library.

**Decision (user call, 2026-07-01): defer this.** For now, `custom_components/`
work can proceed using `tools/grillcore_emu.py` as an interim, dev-only
decode path (not shippable to end users — see below), while this document
tracks the open work needed to finish a real pure-Python port:

- [ ] Fully trace `FUN_002309ac`'s checksum loop (~line 653-665): confirm it
  sums `input[i mod 6] + input[i mod 6] * key32[i]` for `i in 0..31`
  (as read so far) into a single `uVar12`, and how `uVar12` seeds the
  per-row additive constant `cVar6` used in the whitening loop.
- [ ] Fully trace which of `__ptr_00`/`__ptr_01`/`__ptr_02`/`__ptr_03`
  (or their whitened copies) map to `FUN_00231934`'s `param_2` (key,
  passed through `FUN_00214238` for schedule expansion), `param_3`
  (block/state), and `param_4` (per-call tweak) for BOTH calls per row.
  Recorded so far: call 1 uses whitened-`__ptr_00`/whitened-`__ptr_01`/raw-
  `__ptr_02`; call 2 uses the same whitened buffers again with raw-`__ptr_03`.
- [ ] Once the argument mapping is nailed down, either hand-port the exact
  fixslice round function (`FUN_00213f44` et al., dense bit-permutation
  code) or confirm it's swappable for a standard AES-256 library call once
  fed the CORRECT (derived) key/block — re-run the black-box byte-flip test
  against that corrected hypothesis.
- [ ] Repeat for the 23-byte half (may reuse the same `FUN_002309ac`/
  `FUN_00231934` structure, needs confirming — the length-16-vs-different
  branch inside `FUN_00230460` suggests some handling may differ).

## Distribution: emulator is a dev tool only, NOT shipped

`tools/grillcore_emu.py` is a Unicorn AArch64 emulator that loads the real
`.so` and can call its internal functions directly (`decode_advert()`,
`encrypt_data()`, `decrypt_data()`, etc.) — extremely useful for verifying
reverse-engineering work quickly and correctly, since it runs the *actual*
Rust/AES code instead of a hand-ported reimplementation.

**However, per `CLAUDE.md`, `libgrillcore_android.so` may never be
committed and cannot be redistributed to end users.** The emulator is
therefore a **reverse-engineering oracle only**: use it to verify a
from-scratch pure-Python port of the advert crypto (`FUN_002309ac`'s
whitening/checksum step + the fixslice AES-256 core) byte-for-byte, then
ship only the pure-Python version in `custom_components/ninja_woodfire/` —
never the emulator or the `.so` itself.

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
