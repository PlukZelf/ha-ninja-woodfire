#!/usr/bin/env python3
"""Dump BLE GATT services and optionally listen for notifications.

This tool is read-only by default. It connects to a device, lists services and
characteristics, and can subscribe to notify/indicate characteristics. It never
writes characteristic payloads.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from bleak import BleakClient


NINJA_SERVICE_UUID = "0000fcbb-0000-1000-8000-00805f9b34fb"
NINJA_READ_UUID = "0000b001-0000-1000-8000-00805f9b34fb"
NINJA_WRITE_UUID = "0000b002-0000-1000-8000-00805f9b34fb"
NINJA_NOTIFY_UUID = "0000b003-0000-1000-8000-00805f9b34fb"
NINJA_INDICATE_UUID = "0000b004-0000-1000-8000-00805f9b34fb"
GAP_DEVICE_NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True)
class CharacteristicDump:
    uuid: str
    handle: int
    description: str
    properties: list[str]


@dataclass(frozen=True)
class ServiceDump:
    uuid: str
    handle: int
    description: str
    characteristics: list[CharacteristicDump]


def _bytes_to_hex(data: bytes | bytearray) -> str:
    return bytes(data).hex(" ")


def _known_label(uuid: str) -> str | None:
    labels = {
        NINJA_SERVICE_UUID: "Ninja service",
        NINJA_READ_UUID: "Ninja read",
        NINJA_WRITE_UUID: "Ninja write",
        NINJA_NOTIFY_UUID: "Ninja notify",
        NINJA_INDICATE_UUID: "Ninja indicate",
        GAP_DEVICE_NAME_UUID: "Device name",
    }
    return labels.get(uuid.lower())


def dump_services_from_client(client: BleakClient) -> list[ServiceDump]:
    services = client.services
    return [
        ServiceDump(
            uuid=service.uuid,
            handle=service.handle,
            description=service.description,
            characteristics=[
                CharacteristicDump(
                    uuid=characteristic.uuid,
                    handle=characteristic.handle,
                    description=characteristic.description,
                    properties=sorted(characteristic.properties),
                )
                for characteristic in service.characteristics
            ],
        )
        for service in services
    ]


async def read_characteristics(client: BleakClient, characteristics: list[str]) -> None:
    for uuid in characteristics:
        try:
            data = await client.read_gatt_char(uuid)
        except Exception as err:  # noqa: BLE001 - CLI should report BLE backend errors.
            payload = {
                "captured_at": datetime.now(UTC).isoformat(),
                "characteristic": uuid,
                "label": _known_label(uuid),
                "error": str(err),
            }
        else:
            payload = {
                "captured_at": datetime.now(UTC).isoformat(),
                "characteristic": uuid,
                "label": _known_label(uuid),
                "data_hex": _bytes_to_hex(data),
            }
        print(json.dumps(payload, sort_keys=True), flush=True)


async def listen(client: BleakClient, characteristics: list[str], timeout: float) -> None:
    active: list[str] = []

    def callback(characteristic: Any, data: bytearray) -> None:
        uuid = getattr(characteristic, "uuid", str(characteristic))
        payload = {
            "captured_at": datetime.now(UTC).isoformat(),
            "characteristic": uuid,
            "label": _known_label(uuid),
            "data_hex": _bytes_to_hex(data),
        }
        print(json.dumps(payload, sort_keys=True), flush=True)

    for uuid in characteristics:
        await client.start_notify(uuid, callback)
        active.append(uuid)
        print(f"Listening on {uuid} ({_known_label(uuid) or 'unknown'})", flush=True)

    try:
        await asyncio.sleep(timeout)
    finally:
        for uuid in active:
            await client.stop_notify(uuid)


def print_text(services: list[ServiceDump]) -> None:
    for service in services:
        service_label = _known_label(service.uuid)
        suffix = f" ({service_label})" if service_label else ""
        print(f"Service {service.uuid}{suffix}")
        print(f"  Handle: {service.handle}")
        print(f"  Description: {service.description}")
        for characteristic in service.characteristics:
            characteristic_label = _known_label(characteristic.uuid)
            characteristic_suffix = f" ({characteristic_label})" if characteristic_label else ""
            print(f"  Characteristic {characteristic.uuid}{characteristic_suffix}")
            print(f"    Handle: {characteristic.handle}")
            print(f"    Properties: {', '.join(characteristic.properties) or '<none>'}")
            print(f"    Description: {characteristic.description}")
        print()


def print_json(services: list[ServiceDump]) -> None:
    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "services": [asdict(service) for service in services],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dump BLE GATT services for a device.")
    parser.add_argument("address", help="Bluetooth address to connect to.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON service output.",
    )
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Listen on the known Ninja notify and indicate characteristics after dumping services.",
    )
    parser.add_argument(
        "--read-known",
        action="store_true",
        help="Read known safe read characteristics and print JSON lines.",
    )
    parser.add_argument(
        "--listen-timeout",
        type=float,
        default=60.0,
        help="Notification listen duration in seconds. Default: 60.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    async with BleakClient(args.address) as client:
        services = dump_services_from_client(client)
        if args.json:
            print_json(services)
        else:
            print_text(services)

        if args.read_known:
            await read_characteristics(
                client,
                characteristics=[GAP_DEVICE_NAME_UUID, NINJA_READ_UUID],
            )

        if args.listen:
            await listen(
                client,
                characteristics=[NINJA_NOTIFY_UUID, NINJA_INDICATE_UUID],
                timeout=args.listen_timeout,
            )


if __name__ == "__main__":
    asyncio.run(main())
