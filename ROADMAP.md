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

There are TWO separate BLE channels with unrelated crypto (see
[docs/crypto-status.md](docs/crypto-status.md) for full technical detail):
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
- [x] Port the advertisement crypto to pure Python (`tools/advert_crypto_port.py`,
      static AES-256-CBC with fixed key/IV, no emulator/`.so` needed at
      runtime — verified byte-for-byte against 150+ vectors, see
      "Pure-Python port — DONE" in docs/crypto-status.md).
- [ ] Finish mapping the remaining fields (preheat progress, the `extra_byte`
      after the MAC, the rolling final field, probe2 once tested with a
      second physical probe).
- [ ] Capture status notifications during normal app usage or direct GATT
      sessions to start on the (separate, still fully open) GATT command
      channel.
- [ ] Identify command writes for safe read-only and control operations
      over GATT.
- [x] Create a structured protocol specification in `spec/` (GATT service
      shape) and `docs/crypto-status.md` (crypto + field findings).

## Sprint 3: Home Assistant Integration

- [x] Add the custom integration manifest.
- [x] Implement config flow and Bluetooth discovery.
- [x] Add coordinator and device client (passive advertisement scanner).
- [x] Add first read-only entities (sensors + binary sensors).
- [x] Add tests for parsing (`tests/test_advert.py`).
- [ ] Verify manufacturer-data extraction on a real Home Assistant host
      (implemented but not yet tested live — see the known risk in
      ARCHITECTURE.md).

## Sprint 4: Read-Only Polish

- [x] Ship a pure-Python advertisement decoder (no vendor `.so` needed).
- [ ] Finish confirming advertisement field semantics against live cook
      sessions (see the open items in Sprint 2 and docs/crypto-status.md).
- [ ] Document known device models and firmware behavior.
- [ ] Prepare a first tagged release.

## Control entities — not planned

Control entities (cook function, cook type, target temperature, cook time,
wood flavor, start/stop) were prototyped and then **removed**: sending
commands requires the GATT command channel, whose per-session encryption is
unsolved and not derivable offline (see
[docs/crypto-status.md](docs/crypto-status.md)). Until that crypto is broken,
this integration stays read-only and no control entities are on the roadmap.
