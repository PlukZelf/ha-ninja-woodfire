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

## Dump GATT Services

Once the device address is known locally, connect and list GATT services:

```bash
python tools/ble_gatt_dump.py <device-address>
```

Save machine-readable output locally:

```bash
python tools/ble_gatt_dump.py <device-address> --json > captures/gatt-local.json
```

The GATT dump tool is read-only. It connects and inspects services, but does not write to characteristics.

Read known safe characteristics:

```bash
python tools/ble_gatt_dump.py <device-address> --read-known
```

## Listen For Notifications

To listen on the currently known Ninja notify and indicate characteristics:

```bash
python tools/ble_gatt_dump.py <device-address> --listen --listen-timeout 120
```

While this is running, change appliance state from the device controls or the official app and record the emitted payloads.

Do not run unknown write commands against the appliance.

## Parse Android HCI Snoop Logs

If an Android bugreport contains `btsnoop_hci.log`, extract ATT/GATT events with:

```bash
python tools/parse_btsnoop_att.py <path-to-btsnoop_hci.log>
```

To focus on write requests and write commands:

```bash
python tools/parse_btsnoop_att.py <path-to-btsnoop_hci.log> --writes-only
```

Android and BlueZ may assign different numeric handles for the same characteristics, so map handles through nearby service discovery and characteristic properties instead of assuming Linux handle numbers always match Android handle numbers.
