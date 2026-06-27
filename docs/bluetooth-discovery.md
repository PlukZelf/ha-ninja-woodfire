# Bluetooth Discovery

This phase discovers what the Ninja Woodfire exposes over Bluetooth Low Energy.

The first tool is read-only. It scans advertisements and does not connect to the appliance or write commands.

## Setup

Create a virtual environment on the machine that can see the appliance over Bluetooth:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
```

On Linux, the user running the scan may need Bluetooth permissions. On a Raspberry Pi or Home Assistant host, run the scan close to the appliance and make sure the Ninja mobile app is not actively connected.

## Scan Nearby Devices

```bash
python tools/ble_scan.py --timeout 15
```

Filter by advertised name:

```bash
python tools/ble_scan.py --timeout 20 --name ninja
```

Save JSON output locally:

```bash
python tools/ble_scan.py --timeout 20 --name ninja --json > captures/ble-scan-local.json
```

By default, Bluetooth addresses are redacted so scan output is safer to share. If the raw address is needed for a local follow-up command, use:

```bash
python tools/ble_scan.py --timeout 20 --name ninja --show-addresses
```

Do not commit raw addresses or other personal capture data.

## What To Record

For candidate Ninja devices, record:

- advertised name;
- service UUIDs;
- manufacturer data company IDs;
- RSSI range;
- whether the device appears only when powered on, paired, or in a specific mode.

Confirmed, sanitized findings should be documented in `spec/`.
