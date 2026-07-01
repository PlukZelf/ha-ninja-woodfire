# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project intends to follow semantic versioning once releases begin.

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

- The advertisement decoder currently depends on the proprietary vendor
  `.so` (via the emulator) and cannot ship to end users as-is; a pure-Python
  port is planned but paused (see `docs/crypto-status.md`).
- The GATT channel (needed to send commands) remains unsolved; its session
  key is negotiated fresh per connection and not derivable offline.
