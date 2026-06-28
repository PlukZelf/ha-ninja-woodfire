#!/usr/bin/env python3
"""Parse a btsnoop_hci.log and extract Ninja Woodfire ATT traffic.

Focuses on the vendor characteristics:
  b002 (write)  - commands from app to grill
  b004 (indicate) - state from grill to app

Shows hex payloads so we can analyse the encryption offline.

Usage:
  python3 parse_ninja_snoop.py <btsnoop_hci.log> [--label NAME]
"""

from __future__ import annotations

import argparse
import struct
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

WRITE_OPS = (0x12, 0x52)
NOTIFY_OPS = (0x1B, 0x1D)


def bytes_to_hex(data: bytes) -> str:
    return data.hex(" ")


def parse_btsnoop(path: Path):
    data = path.read_bytes()
    if data[:8] != BTSNOOP_MAGIC:
        raise ValueError(f"{path} is not a BTSnoop file")

    offset = 16
    frame = 0
    events = []

    while offset + 24 <= len(data):
        orig_len, incl_len, flags, drops, ts = struct.unpack(
            ">IIIIQ", data[offset:offset + 24]
        )
        offset += 24
        packet = data[offset:offset + incl_len]
        offset += incl_len
        frame += 1

        ev = parse_att(frame, flags, ts, packet)
        if ev:
            events.append(ev)

    return events


def parse_att(frame, flags, ts, packet):
    # HCI ACL data packet = 0x02
    if not packet or packet[0] != 0x02 or len(packet) < 9:
        return None

    handle_pb_bc, acl_len = struct.unpack("<HH", packet[1:5])
    acl = packet[5:5 + acl_len]
    if len(acl) < 5:
        return None

    l2cap_len, cid = struct.unpack("<HH", acl[:4])
    if cid != ATT_CID:
        return None

    att = acl[4:4 + l2cap_len]
    if not att:
        return None

    opcode = att[0]
    handle = None
    value = b""

    if opcode in WRITE_OPS and len(att) >= 3:
        handle = struct.unpack("<H", att[1:3])[0]
        value = att[3:]
    elif opcode in NOTIFY_OPS and len(att) >= 3:
        handle = struct.unpack("<H", att[1:3])[0]
        value = att[3:]
    elif opcode == 0x0B:
        value = att[1:]
    elif opcode in (0x02, 0x03) and len(att) >= 3:
        mtu = struct.unpack("<H", att[1:3])[0]
        value = b""
        return {"frame": frame, "ts": ts, "opcode": opcode,
                "name": f"MTU={mtu}", "handle": None, "value": b"",
                "direction": "?", "is_write": False, "is_notify": False}
    else:
        return None

    # Direction: flags bit 0 indicates received (device->host) on many stacks
    direction = "RX (grill->app)" if (flags & 0x01) else "TX (app->grill)"

    return {
        "frame": frame,
        "ts": ts,
        "opcode": opcode,
        "name": ATT_NAMES.get(opcode, f"op 0x{opcode:02x}"),
        "handle": handle,
        "value": value,
        "direction": direction,
        "is_write": opcode in WRITE_OPS,
        "is_notify": opcode in NOTIFY_OPS,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--min-len", type=int, default=0,
                    help="Only show payloads at least this many bytes")
    args = ap.parse_args()

    events = parse_btsnoop(args.path)

    # Filter to interesting writes/notifications with payload
    interesting = [
        e for e in events
        if (e["is_write"] or e["is_notify"]) and len(e["value"]) >= args.min_len
    ]

    label = f" [{args.label}]" if args.label else ""
    print(f"=== Ninja ATT traffic{label} ===")
    print(f"File: {args.path}")
    print(f"Total ATT events: {len(events)}, payload events: {len(interesting)}")
    print()

    writes = [e for e in interesting if e["is_write"]]
    notifies = [e for e in interesting if e["is_notify"]]

    print(f"--- WRITES (app -> grill), {len(writes)} total ---")
    for e in writes:
        print(f"frame={e['frame']:05d} handle=0x{e['handle']:04x} "
              f"len={len(e['value']):3d} {e['direction']}")
        print(f"   {bytes_to_hex(e['value'])}")
    print()

    print(f"--- INDICATIONS/NOTIFICATIONS (grill -> app), {len(notifies)} total ---")
    for e in notifies:
        print(f"frame={e['frame']:05d} handle=0x{e['handle']:04x} "
              f"len={len(e['value']):3d} {e['direction']}")
        print(f"   {bytes_to_hex(e['value'])}")
    print()

    # Length histogram - helps spot structure
    from collections import Counter
    wlen = Counter(len(e["value"]) for e in writes)
    nlen = Counter(len(e["value"]) for e in notifies)
    print("Write payload lengths:", dict(sorted(wlen.items())))
    print("Notify payload lengths:", dict(sorted(nlen.items())))


if __name__ == "__main__":
    main()
