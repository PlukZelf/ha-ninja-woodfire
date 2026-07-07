# HA Ninja Woodfire

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<img src="assets/icon-512.png" alt="Ninja Woodfire icon" width="88" align="left" hspace="16" />

A local Home Assistant integration for the Ninja Woodfire Pro outdoor grill. It reads the grill's state directly from its Bluetooth Low Energy advertisements, so there's no cloud, no Ninja account, and no proprietary binary involved.

**This is a work in progress.** The integration listens passively to the grill's BLE broadcasts and decodes them locally — it never connects to the grill, so it never conflicts with the Ninja mobile app. The advertisement encryption has been fully reverse-engineered and ported to pure Python, so state reading works without any phone or vendor library, and this has been confirmed working end-to-end on a real Home Assistant host. See [ROADMAP.md](ROADMAP.md) for where things stand.

<br clear="left" />

## What works today

- **Passive** BLE advertisement decoding — no connection to the grill, no pairing, no interference with the Ninja app.
- Read-only sensors and binary sensors for grill state, decoded locally from the broadcast packets.

There are **no control entities** (start/stop cook, set temperature, etc.). Sending commands would require the grill's GATT command channel, whose **per-session** encryption is not yet solved. Recent reverse-engineering has confirmed the grill accepts a from-scratch local BLE client (no app, no cloud) and has captured the plaintext state and command formats — the one remaining blocker is deriving the per-connection session key from the grill's handshake.

## Supported devices

Developed against a **Ninja Woodfire Pro Connect XL**. Other Woodfire models are likely compatible but haven't been tested. If you have one, captures and reports are welcome.

## Requirements

- Home Assistant Core 2026.6.0 or newer.
- A Bluetooth adapter reachable by HA (built-in or USB dongle) that can receive the grill's advertisements.
- `pycryptodome` (declared in the manifest; Home Assistant installs it automatically).

No proprietary vendor library or ARM64-specific binary is required — decoding is pure Python.

## Installation

### HACS

1. HACS → Integrations → ⋮ → *Custom repositories*.
2. Add `https://github.com/PlukZelf/ha-ninja-woodfire` as an *Integration*.
3. Install **Ninja Woodfire** and restart Home Assistant.

### Manual

```bash
cp -r custom_components/ninja_woodfire /config/custom_components/
```

Then restart Home Assistant.

## Setup

1. Power on the grill and keep it nearby.
2. **Settings → Devices & Services → Add Integration**, search for **Ninja Woodfire**.
3. The grill is usually discovered over Bluetooth automatically. If not, enter its address manually.

## Active scanning required

The grill splits its state across two BLE payloads: one rides in the regular advertisement, the other in the **scan response**. The scan response is only sent to scanners that do *active* scanning — a passive-only Bluetooth adapter will only ever see half the data, and the integration will never be able to decode the grill's state.

Home Assistant's built-in Bluetooth integration uses active scanning by default, so this normally works out of the box. If passive scanning has been enabled (directly on the adapter, or on an ESPHome Bluetooth proxy), the integration detects that it's only receiving the 20-byte half and raises a **Repair** issue in Home Assistant explaining what to do.

To fix it:

1. **Settings → Devices & Services → Bluetooth**, click **Configure** on your Bluetooth adapter.
2. Disable **Passive scanning**.
3. If the grill is received through an ESPHome Bluetooth proxy, enable active scanning in that proxy's configuration instead.

## Entities

The integration is read-only. Some fields are only populated in the relevant cook state (for example, probe temperatures need a probe plugged in).

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.ninja_woodfire_state` | Idle / Preheating / Cooking / Complete / Error / Off |
| `sensor.ninja_woodfire_cook_mode` | Grill / Smoke / AirCrisp / Roast / Bake / Broil / Dehydrate / MaxRoast / SlowCook |
| `sensor.ninja_woodfire_oven_current_temp` | Current oven/grill temperature |
| `sensor.ninja_woodfire_oven_target_temp` | Target temperature |
| `sensor.ninja_woodfire_time_left` | Cook time remaining |
| `sensor.ninja_woodfire_time_set` | Total cook time set |
| `sensor.ninja_woodfire_cook_progress` | Cook progress (%) |
| `sensor.ninja_woodfire_preheat_progress` | Preheat progress (%) |
| `sensor.ninja_woodfire_probe1_temp` | Probe 1 temperature |
| `sensor.ninja_woodfire_probe1_target` | Probe 1 target |
| `sensor.ninja_woodfire_probe2_temp` | Probe 2 temperature |
| `sensor.ninja_woodfire_probe2_target` | Probe 2 target |
| `sensor.ninja_woodfire_error_code` | Device error code |

### Binary sensors

| Entity | Description |
|--------|-------------|
| `binary_sensor.ninja_woodfire_connected` | Grill seen (advertising) recently |
| `binary_sensor.ninja_woodfire_lid_open` | Lid open/closed |
| `binary_sensor.ninja_woodfire_cooking` | Currently cooking |
| `binary_sensor.ninja_woodfire_preheating` | Currently preheating |
| `binary_sensor.ninja_woodfire_wood_fire` | Woodfire/smoke active |
| `binary_sensor.ninja_woodfire_probe1_plugged` | Probe 1 plugged in |
| `binary_sensor.ninja_woodfire_probe2_plugged` | Probe 2 plugged in |

Individual field semantics are still being confirmed against live cook sessions.

## Development

### Layout

```
custom_components/ninja_woodfire/   HA integration
  __init__.py                       Setup and teardown
  manifest.json                     Integration manifest
  config_flow.py                    Config flow (discovery + manual)
  coordinator.py                    Passive-scan data coordinator
  bluetooth.py                      Passive BLE advertisement listener
  crypto.py                         Advertisement decrypt (pure Python AES)
  advert_decode.py                  Bit-field decoder
  advert.py                         Decrypt + decode + state mapping
  protocol.py                       Shared state types
  sensor.py / binary_sensor.py      Entities
  diagnostics.py                    HA diagnostics
docs/                               Project notes
spec/gatt.md                        GATT services and characteristics (reference only)
captures/                           Local BLE captures (gitignored)
tests/                              Tests
```

`ARCHITECTURE.md` covers how the pieces fit together; `spec/gatt.md` documents the GATT protocol for reference (the integration does not use GATT).

### Protocol status

The device uses two separate BLE channels with unrelated encryption:

- **Advertisements** (no connection needed): fully decoded and ported to pure Python (`custom_components/ninja_woodfire/crypto.py`) — a static AES-256-CBC decrypt with a fixed key/IV, verified byte-for-byte against the vendor library. This is the channel the integration uses.
- **GATT** (used for reading richer state and sending commands): partially reverse-engineered but not yet usable. What's known so far:
  - The grill accepts a **from-scratch local BLE client** (proven with `bleak` — no app, no cloud, no account) and streams encrypted state on characteristic `b004`.
  - The **plaintext state format** (a device-id header + state fields) and the **command format** (simple JSON — `{"cmd": ..., "data": [...]}`) have both been captured.
  - The GATT encryption key is **per-session** — established fresh by a handshake on every connection and not baked into the vendor library (confirmed from three independent angles). Each encrypted message also carries a per-message nonce.
  - The single remaining blocker is reversing that handshake's **key-derivation** (challenge → session key). Until it's solved, GATT state can't be decrypted locally and no commands can be sent — which is why no control entities exist.

### Tests

```bash
pytest tests/ -v
```

## Contributing

Help is especially useful with:

- BLE captures in different states (cooking, preheating, various modes).
- Confirming advertisement field semantics against known grill state.
- Testing on other Ninja Woodfire models.

See [CONTRIBUTING.md](CONTRIBUTING.md) first. Changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## Disclaimer

Unofficial and independent — not affiliated with or endorsed by SharkNinja. "Ninja" and "Woodfire" are trademarks of SharkNinja Operating LLC.

## License

MIT — see [LICENSE](LICENSE).
