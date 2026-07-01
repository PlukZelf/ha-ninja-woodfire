# Architecture

## Overview

The integration is intended to run fully locally inside Home Assistant. It will communicate with the Ninja Woodfire Pro device over Bluetooth Low Energy and translate device state into Home Assistant entities.

The project is split into three layers:

1. Bluetooth client: connects to the device, subscribes to notifications, and writes commands.
2. Protocol layer: parses notification payloads and builds command payloads.
3. Home Assistant integration: exposes devices, entities, config flow, diagnostics, and repairs.

## Bluetooth Strategy

The device exposes state through **two separate BLE channels with unrelated
encryption** (see [docs/crypto-status.md](docs/crypto-status.md) for the full
reverse-engineering detail):

1. **Passive advertisements** — broadcast continuously, no connection
   needed. Encrypted with a **static** AES-256 key (embedded in the vendor
   app's native library, not per-device/per-session). Fully decoded as of
   2026-07-01: the 344-bit field layout is known and correlated against real
   cook sessions for cook mode, temperatures, cook time, and probe state.
   This is the preferred path for **read-only monitoring** — it needs no BLE
   connection at all, so it never conflicts with the Ninja mobile app (see
   `switch.ninja_woodfire_connection_enabled`, which only matters for the
   GATT path below).
2. **GATT** (after `Connect`) — a per-session key negotiated fresh on every
   connection, held only in-memory on both ends, never persisted. Unsolved.
   Needed only for **sending commands** (temperature/mode/timer changes,
   start/stop cook) — out of scope until reverse-engineered separately.

The previous investigation showed that obtaining Android HCI logs can be
unreliable on recent Pixel devices. The preferred path for further protocol
work is direct discovery from the Raspberry Pi or the Home Assistant host
using Python and `bleak`, or (for the advert channel specifically)
`tools/live_decode.py`, which decodes passing adverts continuously without
needing a phone at all.

Initial tooling should:

- scan for nearby BLE devices;
- connect to the Ninja device;
- list services and characteristics;
- subscribe to candidate notification characteristics;
- log raw payloads with timestamps;
- avoid writing commands until their meaning is understood.

## Expected Home Assistant Structure

```text
custom_components/ninja_woodfire/
  __init__.py
  manifest.json
  config_flow.py
  const.py
  coordinator.py
  bluetooth.py
  protocol.py
  sensor.py
  switch.py
  number.py
  select.py
  diagnostics.py
```

The exact entity set should follow the discovered protocol rather than assumptions from the mobile app.

## Data Flow

```text
Ninja Woodfire Pro
  -> BLE notifications
  -> Bluetooth client
  -> Protocol parser
  -> Data coordinator
  -> Home Assistant entities
```

Control commands should flow in the opposite direction only after the protocol has been documented and validated.

## Safety Notes

Cooking appliances should be treated conservatively. The integration should not send unknown payloads, bypass safety states, or expose controls before the valid ranges and device behavior are understood.

The first working version should prefer read-only monitoring. Control can be added later with explicit validation and clear error handling.
