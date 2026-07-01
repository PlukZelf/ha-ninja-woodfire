#!/usr/bin/env python3
"""Analyse a btsnoop_hci.log for the Ninja Woodfire BLE pairing handshake.

Maps HCI connection handles to device MACs, isolates the connection to a target
MAC, and prints the ordered ATT traffic (writes app->grill, indications
grill->app) that makes up the session-key handshake.

Given two logs it diffs the app->grill write payloads to reveal whether the app
injects per-session randomness (differs) or the handshake is deterministic
(identical) -- which decides how the emulator must replay it.

Usage:
  python analyze_ninja_handshake.py <log> [--mac aabbccddeeff]
  python analyze_ninja_handshake.py --diff <logA> <logB> [--mac ...]
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

BTSNOOP_MAGIC = b"btsnoop\0"
ATT_CID = 0x0004

ATT_NAMES = {
    0x01: "Error Response", 0x02: "MTU Req", 0x03: "MTU Resp",
    0x0A: "Read Req", 0x0B: "Read Resp", 0x12: "Write Req",
    0x13: "Write Resp", 0x1B: "Notify", 0x1D: "Indicate",
    0x1E: "Confirm", 0x52: "Write Cmd",
}
WRITE_OPS = (0x12, 0x52)
NOTIFY_OPS = (0x1B, 0x1D)


def mac_str(b6: bytes) -> str:
    # HCI gives the address little-endian; print big-endian no separators
    return b6[::-1].hex()


def iter_records(path: Path):
    """Yield (frame, flags, hci_packet_bytes) from a btsnoop file."""
    data = path.read_bytes()
    if data[:8] != BTSNOOP_MAGIC:
        raise ValueError(f"{path} is not a BTSnoop file")
    off = 16
    frame = 0
    while off + 24 <= len(data):
        orig_len, incl_len, flags, drops, ts = struct.unpack(
            ">IIIIQ", data[off:off + 24])
        off += 24
        pkt = data[off:off + incl_len]
        off += incl_len
        frame += 1
        yield frame, flags, ts, pkt


def build_handle_mac_map(path: Path) -> dict[int, str]:
    """Parse HCI events for (LE) Connection Complete -> handle:MAC."""
    handle_mac: dict[int, str] = {}
    for frame, flags, ts, pkt in iter_records(path):
        if not pkt or pkt[0] != 0x04:  # HCI Event
            continue
        if len(pkt) < 3:
            continue
        evt = pkt[1]
        # Connection Complete (BR/EDR) 0x03: status, handle(2), bdaddr(6)
        if evt == 0x03 and len(pkt) >= 11:
            status, handle = pkt[3], struct.unpack("<H", pkt[4:6])[0]
            bd = pkt[6:12]
            if status == 0:
                handle_mac[handle & 0x0FFF] = mac_str(bd)
        # LE Meta 0x3e -> subevent
        elif evt == 0x3e and len(pkt) >= 4:
            sub = pkt[3]
            # LE Connection Complete 0x01 / Enhanced 0x0a
            if sub in (0x01, 0x0a) and len(pkt) >= 13:
                status = pkt[4]
                handle = struct.unpack("<H", pkt[5:7])[0] & 0x0FFF
                # role(1), peer_addr_type(1), peer_addr(6) start at offset 8
                bd = pkt[9:15] if sub == 0x01 else pkt[9:15]
                if status == 0 and len(pkt) >= 15:
                    handle_mac[handle] = mac_str(bd)
    return handle_mac


def parse_att(flags: int, pkt: bytes):
    """Return (conn_handle, opcode, att_handle, value) for an ACL ATT packet."""
    if not pkt or pkt[0] != 0x02 or len(pkt) < 9:
        return None
    handle_pb_bc, acl_len = struct.unpack("<HH", pkt[1:5])
    conn = handle_pb_bc & 0x0FFF
    acl = pkt[5:5 + acl_len]
    if len(acl) < 5:
        return None
    l2cap_len, cid = struct.unpack("<HH", acl[:4])
    if cid != ATT_CID:
        return None
    att = acl[4:4 + l2cap_len]
    if not att:
        return None
    op = att[0]
    h = val = None
    if op in WRITE_OPS and len(att) >= 3:
        h = struct.unpack("<H", att[1:3])[0]; val = att[3:]
    elif op in NOTIFY_OPS and len(att) >= 3:
        h = struct.unpack("<H", att[1:3])[0]; val = att[3:]
    elif op == 0x0B:
        val = att[1:]
    else:
        return None
    return conn, op, h, val


def extract(path: Path, target_mac: str | None):
    handle_mac = build_handle_mac_map(path)
    events = []
    for frame, flags, ts, pkt in iter_records(path):
        r = parse_att(flags, pkt)
        if not r:
            continue
        conn, op, h, val = r
        mac = handle_mac.get(conn)
        if target_mac and mac and mac.lower() != target_mac.lower():
            continue
        rx = bool(flags & 0x01)  # received: device -> host
        events.append({
            "frame": frame, "conn": conn, "mac": mac, "op": op,
            "handle": h, "value": val or b"",
            "dir": "RX grill->app" if rx else "TX app->grill",
            "is_write": op in WRITE_OPS, "is_notify": op in NOTIFY_OPS,
        })
    return handle_mac, events


def print_session(path: Path, target_mac: str | None):
    handle_mac, events = extract(path, target_mac)
    print(f"=== {path.name} ===")
    print(f"Connections (handle -> MAC): " +
          ", ".join(f"0x{h:x}:{m}" for h, m in handle_mac.items()) or "none")
    payload = [e for e in events if e["value"]]
    print(f"ATT payload events for target: {len(payload)}\n")
    for e in payload:
        tag = "W" if e["is_write"] else ("I" if e["is_notify"] else "R")
        print(f"  f{e['frame']:05d} {tag} h=0x{e['handle'] or 0:04x} "
              f"len={len(e['value']):3d} {e['dir']}  {e['value'].hex(' ')}")
    return [e for e in payload if e["is_write"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+", type=Path)
    ap.add_argument("--mac", default=None, help="target MAC, e.g. aabbccddeeff")
    ap.add_argument("--diff", action="store_true",
                    help="diff app->grill writes across two logs")
    args = ap.parse_args()

    if args.diff:
        assert len(args.logs) == 2, "--diff needs exactly two logs"
        wa = print_session(args.logs[0], args.mac)
        print()
        wb = print_session(args.logs[1], args.mac)
        print("\n=== WRITE DIFF (app->grill) ===")
        for i, (a, b) in enumerate(zip(wa, wb)):
            same = a["value"] == b["value"]
            print(f"  write[{i}] len={len(a['value'])}/{len(b['value'])} "
                  f"{'IDENTICAL' if same else 'DIFFERS -> app randomness'}")
            if not same:
                va, vb = a["value"], b["value"]
                diff_pos = [j for j in range(min(len(va), len(vb))) if va[j] != vb[j]]
                print(f"    differing byte offsets: {diff_pos}")
        if len(wa) != len(wb):
            print(f"  NOTE: different write counts: {len(wa)} vs {len(wb)}")
    else:
        for log in args.logs:
            print_session(log, args.mac)
            print()


if __name__ == "__main__":
    main()
