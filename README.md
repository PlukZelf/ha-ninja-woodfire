# HA Ninja Woodfire

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.6%2B-blue)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Local Home Assistant integration for the **Ninja Woodfire Pro** outdoor cooking appliance. Connects via Bluetooth Low Energy — no cloud, no Ninja account required.

> **Status:** Active development — protocol reverse-engineering in progress. Basic BLE connectivity works; full state parsing and control commands are being implemented.

![Ninja Woodfire icon preview](assets/icon-512.png)

---

## Features

- 🔵 **Local BLE connection** — no cloud dependency
- 🌡️ **Temperature sensors** — grill, target, probe 1 & 2
- ⏱️ **Timer** — cook duration and time remaining
- 📊 **Progress** — preheat and cook progress
- 🔥 **State** — Idle, Preheating, Cooking, Complete, Error
- 🪵 **Woodfire** — smoke/woodfire active indicator
- 🔓 **Lid sensor** — open/closed
- 🔌 **Probe detection** — plugged in / active

---

## Supported Devices

| Model | Status |
|-------|--------|
| Ninja Woodfire Pro Connect XL | ✅ Primary test device |
| Other models | 🔄 Likely compatible, untested |

---

## Requirements

| Component | Version |
|-----------|---------|
| Home Assistant OS | — |
| Home Assistant Core | 2026.6.0+ |
| Hardware | ARM64 host (Raspberry Pi 4/5, HA Yellow, HA Green) |
| Bluetooth | Required — built-in or USB dongle |

> **Note:** The integration requires an ARM64 host for full BLE decryption support. On x86_64 hosts the integration will connect but cannot decrypt device state until the protocol is fully documented.

---

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ → *Custom repositories*
2. Add `https://github.com/PlukZelf/ha-ninja-woodfire`, category *Integration*
3. Install **Ninja Woodfire**
4. Restart Home Assistant

### Manual

```bash
cp -r custom_components/ninja_woodfire /config/custom_components/
```

Restart Home Assistant.

---

## Setup

1. Make sure your Ninja Woodfire Pro is powered on and nearby
2. Go to **Settings → Devices & Services → Add Integration**
3. Search for **Ninja Woodfire**
4. The device will be discovered automatically via Bluetooth, or enter the address manually

---

## Entities

### Sensors

| Entity | Description | Status |
|--------|-------------|--------|
| `sensor.ninja_woodfire_state` | Device state (Idle / Preheating / Cooking / Complete / Error) | 🔄 In progress |
| `sensor.ninja_woodfire_cook_mode` | Cook mode (Grill / Smoke / AirCrisp / Roast / Bake / Broil / Dehydrate) | 🔄 In progress |
| `sensor.ninja_woodfire_grill_temperature` | Current grill temperature (°C) | 🔄 In progress |
| `sensor.ninja_woodfire_target_temperature` | Target temperature (°C) | 🔄 In progress |
| `sensor.ninja_woodfire_time_remaining` | Time remaining (seconds) | 🔄 In progress |
| `sensor.ninja_woodfire_cook_duration` | Total cook duration (seconds) | 🔄 In progress |
| `sensor.ninja_woodfire_cook_progress` | Cook progress (%) | 🔄 In progress |
| `sensor.ninja_woodfire_preheat_progress` | Preheat progress (%) | 🔄 In progress |
| `sensor.ninja_woodfire_probe_1_temperature` | Probe 1 temperature (°C) | 🔄 In progress |
| `sensor.ninja_woodfire_probe_1_target` | Probe 1 target temperature (°C) | 🔄 In progress |
| `sensor.ninja_woodfire_probe_2_temperature` | Probe 2 temperature (°C) | 🔄 In progress |
| `sensor.ninja_woodfire_probe_2_target` | Probe 2 target temperature (°C) | 🔄 In progress |

### Binary Sensors

| Entity | Description | Status |
|--------|-------------|--------|
| `binary_sensor.ninja_woodfire_connected` | BLE connection status | ✅ Working |
| `binary_sensor.ninja_woodfire_cooking` | Currently cooking | 🔄 In progress |
| `binary_sensor.ninja_woodfire_preheating` | Currently preheating | 🔄 In progress |
| `binary_sensor.ninja_woodfire_lid` | Lid open/closed | ✅ Working |
| `binary_sensor.ninja_woodfire_woodfire_active` | Woodfire/smoke active | 🔄 In progress |
| `binary_sensor.ninja_woodfire_probe_1_connected` | Probe 1 plugged in | 🔄 In progress |
| `binary_sensor.ninja_woodfire_probe_2_connected` | Probe 2 plugged in | 🔄 In progress |

---

## Architecture

The integration is fully local — it communicates directly with the device over BLE. Device state is parsed and exposed as Home Assistant entities without any cloud connectivity.

---

## Development

### Repository Layout

```
custom_components/ninja_woodfire/   HA integration
  __init__.py                       Setup and teardown
  manifest.json                     Integration manifest
  config_flow.py                    Config flow (auto-discovery + manual)
  coordinator.py                    Data update coordinator
  bluetooth.py                      BLE client
  protocol.py                       Protocol parser
  grillcore_native.py               Native library wrapper (future use)
  sensor.py                         Sensor entities
  binary_sensor.py                  Binary sensor entities
  diagnostics.py                    HA diagnostics support
  lib/                              Native library (not included, see below)
docs/                               Project documentation
spec/                               Protocol specifications
  gatt.md                           GATT services and characteristics
tools/                              BLE discovery and analysis tools
  ble_scan.py                       BLE advertisement scanner
  ble_gatt_dump.py                  GATT service dumper + notification listener
  parse_btsnoop_att.py              Android HCI log parser
captures/                           Local BLE captures (gitignored)
tests/                              Automated tests
```

### Protocol Research

Current status of reverse-engineering:

| Area | Status |
|------|--------|
| GATT services & characteristics | ✅ Complete |
| BLE connection flow | ✅ Documented |
| Encryption mechanism | 🔄 In progress (static .so analysis) |
| State payload parsing | 🔄 In progress |
| Command payload format | ⏳ Pending encryption |

See [`spec/gatt.md`](spec/gatt.md) for full protocol notes.

---

## Test Environment

Developed and tested on:

| Component | Version |
|-----------|---------|
| Home Assistant Core | 2026.6.4 |
| Home Assistant OS | 18.0 |
| Supervisor | 2026.06.2 |
| Test device | Ninja Woodfire Pro Connect XL |

---

## Contributing

Contributions welcome, especially:
- BLE captures with different device states (cooking, preheating, different modes)
- Protocol analysis and documentation
- Testing on different Ninja Woodfire models

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting PRs.

---

## Disclaimer

This is an unofficial, independent project. Not affiliated with or endorsed by SharkNinja. "Ninja", "Woodfire" and related product names are trademarks of SharkNinja Operating LLC.

## License

MIT — see [LICENSE](LICENSE).
