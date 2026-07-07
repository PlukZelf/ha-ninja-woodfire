# Roadmap

## Sprint 0: Repository Foundation

- [x] Create the repository structure.
- [x] Add project documentation placeholders and first content.
- [x] Add an initial GitHub remote.
- [x] Make the first commit.

## Sprint 1: Bluetooth Discovery

- [x] Add a `bleak`-based discovery tool.
- [x] Scan for the Ninja Woodfire Pro device.
- [x] Record GATT services and characteristics.
- [ ] Document notification characteristics and observed payloads.

## Sprint 2: Protocol Research

There are TWO separate BLE channels with unrelated crypto:
the passive **advertisement** channel (static key, fully decoded, no
connection needed) and the **GATT** channel used after `Connect` (per-session
key, unsolved, needed only for sending commands).

- [x] Reverse-engineer the advertisement crypto (static AES-256 + whitening,
      verified via a Unicorn-emulator oracle against the real `.so`).
- [x] Decode the advertisement's full bit-packed field layout (344 bits, 43
      bytes — header + MAC + probe1/probe2 blocks + final field).
- [x] Map field semantics against real cook sessions: cook mode, remaining/
      total cook time, oven temperature, target temperature, probe1
      temperature, probe plugged-in/target-set flags, probe target
      temperature.
- [x] Port the advertisement crypto to pure Python
      (`custom_components/ninja_woodfire/crypto.py`, static AES-256-CBC with
      fixed key/IV, no emulator/`.so` needed at runtime — verified
      byte-for-byte against 150+ vectors).
- [ ] Finish mapping the remaining fields (preheat progress, the `extra_byte`
      after the MAC, the rolling final field, probe2 once tested with a
      second physical probe).
- [ ] Capture status notifications during normal app usage or direct GATT
      sessions to start on the (separate, still fully open) GATT command
      channel.
- [ ] Identify command writes for safe read-only and control operations
      over GATT.
- [x] Create a structured protocol specification in `spec/` (GATT service
      shape).

## Sprint 3: Home Assistant Integration

- [x] Add the custom integration manifest.
- [x] Implement config flow and Bluetooth discovery.
- [x] Add coordinator and device client (passive advertisement scanner).
- [x] Add first read-only entities (sensors + binary sensors).
- [x] Add tests for parsing (`tests/test_advert.py`).
- [x] Verify manufacturer-data extraction on a real Home Assistant host —
      confirmed working live (2026-07-03): both AD-structs decode correctly
      via `service_info.raw` when the adapter scans actively.
- [x] Detect passive-only scanning (the 23-byte advert half only reaches
      active scanners, via the scan response) and raise a Home Assistant
      Repair issue pointing the user at the fix.
- [x] Render cook-time sensors as `H:MM:SS`.

## Sprint 4: Read-Only Polish

- [x] Ship a pure-Python advertisement decoder (no vendor `.so` needed).
- [ ] Finish confirming advertisement field semantics against live cook
      sessions (see the open items in Sprint 2).
- [ ] Document known device models and firmware behavior.
- [ ] Prepare a first tagged release.

## Sprint 5: GATT Command Channel (control) — reverse-engineering in progress

Control entities were previously prototyped and removed, and sending
commands remains unimplemented — but the underlying GATT session-key
reverse-engineering is now **actively in progress**, not parked.

- [x] Phase 1 — confirm the wire protocol: captured a live handshake via
      btsnoop and confirmed the exact framing (CCCD write → 20-byte
      encrypted challenge → uniform 48-byte encrypted writes).
- [x] Phase 3 — offline emulator replay: **ruled out (dead end).** The GATT
      session/crypto path is built on a Rust async runtime (tokio); tracing
      `extProcessBTData` hits a `"tried to use async function in non async
      context"` panic. Unlike the advert crypto (a synchronous leaf function),
      the command crypto needs a live executor + reactor with real BLE I/O,
      which the Unicorn emulator cannot run. The key is not derivable offline.
- [ ] Phase 2 (now the only viable route) — live Frida on the phone:
      **spawn-inject the STOCK app** (`frida -U -f`) with anti-detection
      bypass and hook the crypto exports while a real command is sent,
      capturing plaintext↔ciphertext↔key from the running async runtime. The
      earlier attach attempt failed only because the repackaged Gadget build
      was too unstable to dispatch a command.
- [ ] Once a session key is captured live, design and
      implement control entities (temperature, cook mode, start/stop,
      etc.) — not started, and not guaranteed until the above lands.
