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
etc.) are not yet mapped — this requires live captures correlated against
known grill/app state (idle vs cooking, probe states, etc.) and is the next
piece of work.

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
