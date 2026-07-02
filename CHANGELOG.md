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
  AES-256 + whitening) and full 344-bit field layout, verified via a
  Unicorn-emulator oracle driving the real vendor library
  (`tools/grillcore_emu.py`). See `docs/crypto-status.md`.
- Mapped several advertisement field semantics against real cook sessions:
  cook mode, remaining/total cook time, oven temperature, target
  temperature, probe1 temperature, and probe plugged-in/target-set/target-
  temperature fields.
- Added `tools/live_decode.py`, a phone-free continuous BLE advert decoder
  (works around a Windows/bleak limitation that drops one of the grill's two
  same-company-ID manufacturer-data sections — see `tools/scan_grill_raw.py`).
- Identified the device's cloud backend as Ayla Networks (used for account/
  device registration only — not a shortcut for the local BLE crypto).

### Known limitations

- The GATT channel (needed to send commands) remains unsolved; its session
  key is negotiated fresh per connection and not derivable offline.
