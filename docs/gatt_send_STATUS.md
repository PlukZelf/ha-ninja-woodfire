# GATT Send-Commands — Status Ledger

Single source of truth for progress on the **write/control** path. Every worker
updates this on exit (pass OR blocked). See `docs/send-commands-plan.md` for the
phases, gates, and Execution Protocol (R1–R6).

**States:** `todo` · `in-progress` · `blocked` · `PASS`

| Phase | Objective | State | Gate result | Deliverable |
|------|-----------|-------|-------------|-------------|
| 0 | Consolidate mess + stable rig | `todo` | — | `tools/gatt_send/` + rig README |
| 1 | Reliable session-key capture (linchpin) | `todo` | — | `tools/gatt_send/capture_keys.py` + ≥3 `(challenge,key)` fixtures |
| 2 | Reverse key derivation `f(challenge)→key` | `todo` | — | `gatt_crypto.py::derive_key` |
| 3 | Reverse record enc/dec (b002/b004) | `todo` | — | `gatt_crypto.py::{encrypt,decrypt}_record` |
| 4 | Reverse auth handshake (first 48B) | `todo` | — | `gatt_crypto.py::build_auth_response` |
| 5 | Pure-Python client (laptop end-to-end) | `todo` | — | `tools/gatt_send/ninja_client.py` |
| 6 | HA control entities | `todo` | — | control entities in integration |

## Current next task
**Phase 0.** Create `tools/gatt_send/`, move the working thin/attach-first hook
pattern in as documented tools, preserve the ground-truth fixtures (redacted) into
gitignored `captures/`, and write the stable-rig procedure. Gate: cold-start →
attach thin hook → see live plaintext twice in a row without a crash.

## Blockers / notes
- (none yet)

## Confirmed-closed routes (do not reopen — see plan R4)
- Offline Unicorn emulator replay of GATT path (tokio async wall).
- libcrypto/BoringSSL hook for the GATT key (grillcore uses inlined Rust AES).
- Memory-scan for a contiguous 32B key (bitsliced).
- Anything on the read/advert path (done/shipped) or cloud/Ayla at runtime.
