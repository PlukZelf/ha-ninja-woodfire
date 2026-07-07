# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project intends to follow semantic versioning once releases begin.

## 0.2.0

### Changed

- **Rewrote the integration to passive BLE advertisement scanning.** The
  integration no longer connects to the grill over GATT; it listens to the
  grill's broadcast advertisements and decodes them locally. No connection,
  no pairing, no interference with the Ninja mobile app.
- Ported the advertisement decryption to pure Python
  (`custom_components/ninja_woodfire/crypto.py`, static AES-256-CBC with a
  fixed key/IV). The proprietary vendor `.so` is no longer required by end
  users.
- `manifest.json`: version bumped to 0.2.0, added `pycryptodome>=3.20.0`,
  removed the `bleak-retry-connector` requirement, added a manufacturer-id
  (0x0C4F / 3151) Bluetooth matcher alongside the name-prefix matcher, and
  set `connectable: false` everywhere (no connection is ever made).

### Removed

- All control entities and their modules (`switch.py`, `button.py`,
  `number.py`, `select.py`, `time.py`, `commands.py`) — sending commands
  needs the GATT command channel, whose per-session encryption is unsolved.
- The native-library wrapper (`grillcore_native.py`) and the `lib/`
  directory — no proprietary binary is used anymore.

### Added

- `crypto.py`, `advert_decode.py`, `advert.py`: the shippable
  decrypt + decode + state-mapping pipeline, plus `tests/test_advert.py`.

## Unreleased

### Added

- Initial repository documentation and project structure.
- Read-only BLE advertisement scanner for discovery work.
- Confirmed initial Ninja Woodfire Pro GATT service and characteristic UUIDs.
- Read-only GATT dump and notification listener tool.
- Read-only characteristic reads for known safe GATT endpoints.
- First observed `b004` indicate payload sample.
- Notification capture output now includes payload length.
- BTSnoop ATT parser for Android HCI snoop logs.
- Android HCI capture notes for official app write and indication flow.
- Reverse-engineered the BLE **advertisement** channel's encryption (static
  AES-256 + whitening) and full 344-bit field layout, then ported it to pure
  Python — verified byte-for-byte against the vendor library. This is the
  channel the shipped integration uses.
- Mapped several advertisement field semantics against real cook sessions:
  cook mode, remaining/total cook time, oven temperature, target
  temperature, probe1 temperature, and probe plugged-in/target-set/target-
  temperature fields.
- Identified the device's cloud backend as Ayla Networks (used for account/
  device registration only — not a shortcut for the local BLE crypto).
- Confirmed live on a real Home Assistant host (2026-07-03): manufacturer-data
  extraction from `BluetoothServiceInfoBleak.raw` works end-to-end, decoding
  the grill's full state from passive advertisements.
- Detected and gated on **active scanning**: half of the grill's state (the
  23-byte advert payload) only reaches scanners that do active BLE scanning,
  since it rides in the scan response. The coordinator now detects
  passive-only reception (repeated unpaired 20-byte halves) and raises a
  Home Assistant **Repair** issue explaining how to enable active scanning.
- Cook-time sensors (`time_left`, `time_set`) now render as `H:MM:SS` instead
  of raw seconds.
- GATT command-channel reverse-engineering progress (still unsolved, see
  "Known limitations" below): the handshake wire framing was confirmed from a
  live btsnoop capture (CCCD write, 20-byte encrypted challenge, uniform
  48-byte encrypted writes), and offline emulator replay was ruled out — the
  command crypto runs on a Rust async runtime (tokio) that cannot be driven
  offline the way the advert crypto's leaf function can.

### Known limitations

- The GATT command channel (needed to send commands) remains unsolved.
  Reverse-engineering is in progress: wire protocol confirmed; offline
  emulator replay **ruled out** (the command crypto is async-runtime-bound,
  not an offline-emulatable leaf function like the advert crypto); the
  remaining viable route is a live Frida spawn-inject of the stock app to
  capture the key while a real command is sent. No control entities exist yet.
