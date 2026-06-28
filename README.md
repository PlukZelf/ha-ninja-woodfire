# HA Ninja Woodfire

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2026.6%2B-blue)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Local Home Assistant integration for the **Ninja Woodfire Pro** outdoor cooking appliance. Connects via Bluetooth Low Energy — no cloud, no Ninja account required.

> **Status:** Active development — protocol reverse-engineering in progress. Basic BLE connectivity works; full state parsing and control commands are being implemented.

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
| Ninja Woodfire Pro (OG-series) | ✅ Primary test device |
| Other OG-series | 🔄 Likely compatible, untested |

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

### HACS icon / branding

Gekozen bronbestand: `assets/ninja-woodfire-icon.png`.

Beschikbare varianten:
- `assets/icon.png` (originele resolutie)
- `assets/icon-512.png`
- `assets/icon-256.png`

Voor zichtbaarheid in HACS wordt branding via Home Assistant Brands geleverd. Gebruik deze assets als bron voor een brands-PR onder `custom_integrations/ninja_woodfire`.

---

## Setup

1. Make sure your Ninja Woodfire Pro is powered on and nearby
2. Go to **Settings → Devices & Services → Add Integration**
3. Search for **Ninja Woodfire**
4. The device will be discovered automatically via Bluetooth, or enter the address manually

---

## Entities

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.ninja_woodfire_state` | Device state (Idle / Preheating / Cooking / Complete / Error) |
| `sensor.ninja_woodfire_cook_mode` | Cook mode (Grill / Smoke / AirCrisp / Roast / Bake / Broil / Dehydrate) |
| `sensor.ninja_woodfire_grill_temperature` | Current grill temperature (°C) |
| `sensor.ninja_woodfire_target_temperature` | Target temperature (°C) |
| `sensor.ninja_woodfire_time_remaining` | Time remaining (seconds) |
| `sensor.ninja_woodfire_cook_duration` | Total cook duration (seconds) |
| `sensor.ninja_woodfire_cook_progress` | Cook progress (%) |
| `sensor.ninja_woodfire_preheat_progress` | Preheat progress (%) |
| `sensor.ninja_woodfire_probe_1_temperature` | Probe 1 temperature (°C) |
| `sensor.ninja_woodfire_probe_1_target` | Probe 1 target temperature (°C) |
| `sensor.ninja_woodfire_probe_2_temperature` | Probe 2 temperature (°C) |
| `sensor.ninja_woodfire_probe_2_target` | Probe 2 target temperature (°C) |

### Binary Sensors

| Entity | Description |
|--------|-------------|
| `binary_sensor.ninja_woodfire_connected` | BLE connection status |
| `binary_sensor.ninja_woodfire_cooking` | Currently cooking |
| `binary_sensor.ninja_woodfire_preheating` | Currently preheating |
| `binary_sensor.ninja_woodfire_lid` | Lid open/closed |
| `binary_sensor.ninja_woodfire_woodfire_active` | Woodfire/smoke active |
| `binary_sensor.ninja_woodfire_probe_1_connected` | Probe 1 plugged in |
| `binary_sensor.ninja_woodfire_probe_2_connected` | Probe 2 plugged in |

---

## Architecture

The integration is fully local — it communicates directly with the device over BLE:

```
Ninja Woodfire Pro
  → BLE advertisements (NCEU<mac>)
  → GATT Service: 0000fcbb-0000-1000-8000-00805f9b34fb
    → Indicate (b004): encrypted device state
    → Write (b002): encrypted commands
  → Protocol layer (decrypt + parse)
  → Data coordinator
  → Home Assistant entities
```

### BLE Protocol

The device uses an encrypted BLE protocol:
- **Challenge-response** authentication on connect
- **Session-based encryption** — key derived per connection
- **Indication-based** state updates on characteristic `b004`
- **Write commands** to characteristic `b002`

The encryption is implemented in `libgrillcore_android.so` (Rust, ARM64). Protocol reverse-engineering is ongoing — see [`spec/`](spec/) for current findings.

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

### Running the BLE tools

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt

# Scan for nearby Ninja devices
python tools/ble_scan.py --timeout 20 --name ninja

# Dump GATT services and listen for notifications
python tools/ble_gatt_dump.py <device-address> --listen --listen-timeout 120

# Parse Android HCI log
python tools/parse_btsnoop_att.py path/to/btsnoop_hci.log
```

---

## Test Environment

Developed and tested on:

| Component | Version |
|-----------|---------|
| Home Assistant Core | 2026.6.4 |
| Home Assistant OS | 18.0 |
| Supervisor | 2026.06.2 |
| Test device | Ninja Woodfire Pro (OG-series, EU) |

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
