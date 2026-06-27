#!/usr/bin/env python3
"""Scan for nearby Bluetooth Low Energy devices.

This tool is intentionally read-only. It does not connect to devices and does
not write any Bluetooth characteristics.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from bleak import BleakScanner


@dataclass(frozen=True)
class Advertisement:
    """Serializable BLE advertisement summary."""

    name: str | None
    address: str
    rssi: int | None
    manufacturer_data: dict[str, str]
    service_uuids: list[str]
    service_data: dict[str, str]


def _bytes_to_hex(data: bytes) -> str:
    return data.hex(" ")


def _mask_address(address: str) -> str:
    digest = hashlib.sha256(address.encode("utf-8")).hexdigest()
    return f"redacted-{digest[:12]}"


def _advertisement_from_detection(device: Any, advertisement_data: Any, redact: bool) -> Advertisement:
    manufacturer_data = {
        str(company_id): _bytes_to_hex(data)
        for company_id, data in sorted(advertisement_data.manufacturer_data.items())
    }
    service_data = {
        uuid: _bytes_to_hex(data)
        for uuid, data in sorted(advertisement_data.service_data.items())
    }

    return Advertisement(
        name=device.name or advertisement_data.local_name,
        address=_mask_address(device.address) if redact else device.address,
        rssi=advertisement_data.rssi,
        manufacturer_data=manufacturer_data,
        service_uuids=sorted(advertisement_data.service_uuids),
        service_data=service_data,
    )


async def scan(timeout: float, name_filter: str | None, redact: bool) -> list[Advertisement]:
    seen: dict[str, Advertisement] = {}

    def callback(device: Any, advertisement_data: Any) -> None:
        entry = _advertisement_from_detection(device, advertisement_data, redact)
        if name_filter and name_filter.lower() not in (entry.name or "").lower():
            return
        seen[entry.address] = entry

    scanner = BleakScanner(callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()

    return sorted(
        seen.values(),
        key=lambda item: (item.name is None, item.name or "", item.address),
    )


def print_text(devices: list[Advertisement]) -> None:
    if not devices:
        print("No BLE devices found.")
        return

    for device in devices:
        print(f"Name: {device.name or '<unknown>'}")
        print(f"Address: {device.address}")
        print(f"RSSI: {device.rssi if device.rssi is not None else '<unknown>'}")
        if device.service_uuids:
            print("Service UUIDs:")
            for uuid in device.service_uuids:
                print(f"  - {uuid}")
        if device.manufacturer_data:
            print("Manufacturer data:")
            for company_id, data in device.manufacturer_data.items():
                print(f"  - {company_id}: {data}")
        if device.service_data:
            print("Service data:")
            for uuid, data in device.service_data.items():
                print(f"  - {uuid}: {data}")
        print()


def print_json(devices: list[Advertisement], timeout: float, redact: bool) -> None:
    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "timeout_seconds": timeout,
        "addresses_redacted": redact,
        "devices": [asdict(device) for device in devices],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan for nearby BLE advertisements.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Scan duration in seconds. Default: 10.",
    )
    parser.add_argument(
        "--name",
        help="Only show devices whose advertised name contains this value.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--show-addresses",
        action="store_true",
        help="Show raw Bluetooth addresses. Do not commit this output publicly.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    devices = await scan(
        timeout=args.timeout,
        name_filter=args.name,
        redact=not args.show_addresses,
    )

    if args.json:
        print_json(devices, timeout=args.timeout, redact=not args.show_addresses)
    else:
        print_text(devices)


if __name__ == "__main__":
    asyncio.run(main())
