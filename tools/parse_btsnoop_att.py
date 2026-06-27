#!/usr/bin/env python3
"""Extract ATT/GATT events from an Android btsnoop_hci.log file.

The output is intended for protocol research. It focuses on ATT writes,
notifications, indications, reads, and errors. It does not require Wireshark.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


BTSNOOP_MAGIC = b"btsnoop\0"
ATT_CID = 0x0004

ATT_NAMES = {
    0x01: "Error Response",
    0x02: "Exchange MTU Request",
    0x03: "Exchange MTU Response",
    0x0A: "Read Request",
    0x0B: "Read Response",
    0x12: "Write Request",
    0x13: "Write Response",
    0x1B: "Handle Value Notification",
    0x1D: "Handle Value Indication",
    0x1E: "Handle Value Confirmation",
    0x52: "Write Command",
}


@dataclass(frozen=True)
class AttEvent:
    frame: int
    flags: int
    connection_handle: int
    opcode: int
    handle: int | None
    value: bytes
    detail: str


def _bytes_to_hex(data: bytes) -> str:
    return data.hex(" ")


def _parse_att(frame: int, flags: int, packet: bytes) -> AttEvent | None:
    if not packet or packet[0] != 0x02 or len(packet) < 9:
        return None

    handle_pb_bc, acl_len = struct.unpack("<HH", packet[1:5])
    connection_handle = handle_pb_bc & 0x0FFF
    acl = packet[5 : 5 + acl_len]
    if len(acl) < 5:
        return None

    l2cap_len, cid = struct.unpack("<HH", acl[:4])
    if cid != ATT_CID:
        return None

    att = acl[4 : 4 + l2cap_len]
    if not att:
        return None

    opcode = att[0]
    handle: int | None = None
    value = b""
    detail = ""

    if opcode in (0x12, 0x52, 0x1B, 0x1D) and len(att) >= 3:
        handle = struct.unpack("<H", att[1:3])[0]
        value = att[3:]
    elif opcode == 0x0A and len(att) >= 3:
        handle = struct.unpack("<H", att[1:3])[0]
    elif opcode == 0x0B:
        value = att[1:]
    elif opcode == 0x01 and len(att) >= 5:
        request_opcode = att[1]
        handle = struct.unpack("<H", att[2:4])[0]
        error_code = att[4]
        detail = f"request=0x{request_opcode:02x} error=0x{error_code:02x}"
    elif opcode in (0x02, 0x03) and len(att) >= 3:
        mtu = struct.unpack("<H", att[1:3])[0]
        detail = f"mtu={mtu}"
    else:
        return None

    return AttEvent(
        frame=frame,
        flags=flags,
        connection_handle=connection_handle,
        opcode=opcode,
        handle=handle,
        value=value,
        detail=detail,
    )


def parse_btsnoop(path: Path) -> list[AttEvent]:
    data = path.read_bytes()
    if data[:8] != BTSNOOP_MAGIC:
        raise ValueError(f"{path} is not a BTSnoop file")

    offset = 16
    frame = 0
    events: list[AttEvent] = []

    while offset + 24 <= len(data):
        _original_length, included_length, flags, _drops, _timestamp = struct.unpack(
            ">IIIIQ", data[offset : offset + 24]
        )
        offset += 24
        packet = data[offset : offset + included_length]
        offset += included_length
        frame += 1

        event = _parse_att(frame, flags, packet)
        if event is not None:
            events.append(event)

    return events


def parse_handle(value: str) -> int:
    return int(value, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract ATT events from btsnoop_hci.log.")
    parser.add_argument("path", type=Path, help="Path to btsnoop_hci.log.")
    parser.add_argument(
        "--handle",
        action="append",
        type=parse_handle,
        help="Only show events for this ATT handle. May be used multiple times.",
    )
    parser.add_argument(
        "--writes-only",
        action="store_true",
        help="Only show write requests and write commands.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    handles = set(args.handle or [])
    events = parse_btsnoop(args.path)

    for event in events:
        if handles and event.handle not in handles:
            continue
        if args.writes_only and event.opcode not in (0x12, 0x52):
            continue

        name = ATT_NAMES.get(event.opcode, f"opcode 0x{event.opcode:02x}")
        handle = f"0x{event.handle:04x}" if event.handle is not None else ""
        value = _bytes_to_hex(event.value)
        print(
            f"frame={event.frame:04d} flags=0x{event.flags:x} "
            f"conn=0x{event.connection_handle:x} op=0x{event.opcode:02x} "
            f"{name} handle={handle} len={len(event.value)} "
            f"value={value} {event.detail}".rstrip()
        )


if __name__ == "__main__":
    main()
