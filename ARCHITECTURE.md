# Architecture

## Overview

The integration runs fully locally inside Home Assistant. It reads the Ninja
Woodfire Pro's state from its Bluetooth Low Energy **advertisements** and
translates it into Home Assistant entities. It never connects to the grill,
so it never conflicts with the Ninja mobile app. It is **read-only**.

The project is split into three layers:

1. Bluetooth listener: registers a passive advertisement callback and hands
   the grill's two manufacturer-data payloads to the decoder.
2. Decode layer: decrypts each advertisement payload and unpacks its
   bit-fields into a device-state structure.
3. Home Assistant integration: exposes the device, read-only entities, config
   flow, and diagnostics.

## Bluetooth Strategy

The device exposes state through **two separate BLE channels with unrelated
encryption**:

1. **Passive advertisements** — broadcast continuously, no connection
   needed. Encrypted with a **static** AES-256 key (a fixed key/IV recovered
   from the vendor library, not per-device or per-session). Fully decoded and
   ported to pure Python (`custom_components/ninja_woodfire/crypto.py`),
   verified byte-for-byte against the vendor code. **This is the channel the
   integration uses.** No connection means no conflict with the mobile app.
2. **GATT** (after `Connect`) — a per-session key negotiated fresh on every
   connection, held only in-memory on both ends, never persisted. Unsolved.
   It would be needed only for **sending commands** (temperature/mode/timer
   changes, start/stop cook), which the integration does not do.

## Data Flow

```text
Ninja Woodfire Pro
  -> BLE advertisements (two manufacturer-data payloads, company id 0x0C4F)
  -> Passive Bluetooth callback (bluetooth.py)
  -> Decrypt each half (crypto.py)  +  bit-field decode (advert_decode.py)
  -> State mapping (advert.py)
  -> Data coordinator (coordinator.py, tracks presence by advert recency)
  -> Home Assistant read-only entities
```

There is no reverse (command) path: the GATT command channel's crypto is
unsolved, so the integration exposes no controls.

## Home Assistant Structure

```text
custom_components/ninja_woodfire/
  __init__.py
  manifest.json
  config_flow.py
  const.py
  coordinator.py       passive-scan coordinator
  bluetooth.py         passive advertisement listener
  crypto.py            advertisement decrypt (pure Python AES)
  advert_decode.py     bit-field decoder
  advert.py            decrypt + decode + state mapping
  protocol.py          shared state types
  sensor.py
  binary_sensor.py
  diagnostics.py
```

## Known Risk

The exact extraction of the grill's two manufacturer-data AD structures (both
under company id 0x0C4F, one 20 bytes and one 23 bytes) from Home Assistant's
`BluetoothServiceInfoBleak` object has not yet been verified against a real HA
host. `bluetooth.py` implements a primary path (parsing `service_info.raw`)
and a fallback; this may need debugging once tried live.

## Safety Notes

The integration is read-only and sends nothing to the appliance. If control is
ever added (contingent on solving the GATT command crypto), it must include
explicit range validation and clear error handling before exposing any
controls.
