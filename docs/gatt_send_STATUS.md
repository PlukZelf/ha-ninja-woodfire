# GATT Send-Commands — Status Ledger

Single source of truth for progress on the **write/control** path. Every worker
updates this on exit (pass OR blocked). See `docs/send-commands-plan.md` for the
phases, gates, and Execution Protocol (R1–R6).

**States:** `todo` · `in-progress` · `blocked` · `PASS`

| Phase | Objective | State | Gate result | Deliverable |
|------|-----------|-------|-------------|-------------|
| 0 | Consolidate mess + stable rig | `in-progress` | offline rails in place; rig (0.3) still todo | `tools/gatt_send/` + rig README |
| 1 | Reliable session-key capture (linchpin) | `todo` | — | `tools/gatt_send/capture_keys.py` + ≥3 `(challenge,key)` fixtures |
| 2 | Reverse key derivation `f(challenge)→key` | `todo` | `FAIL` (stub; fixtures absent) | `gatt_crypto.py::derive_key` |
| 3 | Reverse record enc/dec (b002/b004) | `todo` | `FAIL` (stub; fixtures absent) | `gatt_crypto.py::{encrypt,decrypt}_record` |
| 4 | Reverse auth handshake (first 48B) | `todo` | `FAIL` (stub; fixtures absent) | `gatt_crypto.py::build_auth_response` |
| 5 | Pure-Python client (laptop end-to-end) | `todo` | — | `tools/gatt_send/ninja_client.py` |
| 6 | HA control entities | `todo` | — | control entities in integration |

### Scaffolding in place (Phase 0, partial — offline enforcement rails)
The runnable-gate scaffolding for R2 exists (checks FAIL cleanly until the real
phases land, which is correct):
- `tools/gatt_send/gatt_crypto.py` — stub module: `derive_key`, `decrypt_record`,
  `encrypt_record`, `build_auth_response` (each raises `NotImplementedError`).
- `tools/gatt_send/checks/check_phase{2,3,4}.py` — runnable gates; each prints a
  single `PASS`/`FAIL: …` line, no traceback.
- `tools/gatt_send/fixtures/README.md` — the JSON fixture format contract
  (`keys.json`, `state_record.json`, `command_record.json`, `auth_record.json`).
  Fixture `*.json` are gitignored (key material); only the README is committed.
- `tools/gatt_send/README.md` — folder purpose, layout, DO-NOT list.

Still todo in Phase 0/1: **0.3** the stable phone instrumentation rig, and
**Phase 1** the live key capture that produces `fixtures/keys.json` — both need a
human + device.

## Current next task
**Phase 0.3 + Phase 1 (phone-dependent — needs a human + device).** The offline
gate-check scaffolding and fixture contracts are now in place. What remains is
the phone-dependent work autonomous agents cannot do: (0.3) stand up the stable
instrumentation rig — cold-start → attach thin hook → see live plaintext twice in
a row without a crash — and document its exact launch+attach sequence in
`tools/gatt_send/README.md`; then (Phase 1) run the live key capture to produce
≥3 `(challenge, key)` pairs into `tools/gatt_send/fixtures/keys.json`, which makes
`check_phase2.py` runnable against real data.

## Blockers / notes
- **Offline analysis ceiling reached (2026-07-04).** Autonomous offline work done:
  - `tools/analyze_ninja_handshake.py` FIXED (committed) — extracts the full wire
    handshake from `captures/btsnoop-setcmd-last.log`: ~15 sessions of
    `CCCD 02 00` → 20B challenge (h=0x0016) → 48B write (h=0x0011).
  - Wire structural analysis: 48B writes + 20B challenges are **effectively random**
    (no constant bytes, unique 16B prefixes, no ECB tell). Confirms strong
    per-session encryption + per-message IV/nonce; **48B ≈ 16B IV + 32B ciphertext**.
    → No wire-only shortcut; the key is the sole path.
  - Ghidra decompile of the decrypt `FUN_003c3ba0` confirms it is logging + a
    **vtable dispatch** `(*(code**)(*session + 0x558))(...)` into a per-session
    closure — no static cipher/key. Matches the per-session/tokio findings.
- **Command names gap:** only `{"cmd":"Connect"}` is confirmed. The set/cook
  command names + `data[]` schema are NOT in the `.so` or repo artifacts (they live
  in the app's JS/Kotlin layer) → must be captured from a live `extSendBTPayload`
  send (interactive). Needed for Phase 6 entities.
- **What remains needs the phone + human (interactive):** capture the session key.
  Two routes, both need a live session: (A) app-as-driver/oracle — inject our own
  `extSendBTPayload` JSON so the app does the handshake+encrypt (proves control +
  yields matched tuples); (B) hook the key at the moment the key-schedule runs.
  Neither is doable autonomously (needs the app kept connected + change/verify).

## Confirmed-closed routes (do not reopen — see plan R4)
- Offline Unicorn emulator replay of GATT path (tokio async wall).
- libcrypto/BoringSSL hook for the GATT key (grillcore uses inlined Rust AES).
- Memory-scan for a contiguous 32B key (bitsliced).
- Anything on the read/advert path (done/shipped) or cloud/Ayla at runtime.
