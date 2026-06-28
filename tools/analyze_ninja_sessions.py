#!/usr/bin/env python3
"""Analyze Ninja Woodfire BLE sessions from btsnoop captures.

This script groups ATT traffic into sessions and extracts the confirmed
connection flow:

1) CCCD write 0x0002 on handle 0x0017
2) Indication #1 (challenge), 20 bytes on handle 0x0016
3) Write #1 (auth response), 48 bytes on handle 0x0011
4) Indication #2 (auth confirm), 20 bytes
5) Write #2 (state request), 48 bytes
6) Indication #3 (device state), 20 bytes

It works on encrypted payloads and helps compare multiple sessions
without requiring rooted-device hooks.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from parse_ninja_snoop import parse_btsnoop


HANDLE_WRITE = 0x0011   # b002
HANDLE_INDICATE = 0x0016  # b004
HANDLE_CCCD = 0x0017
CCCD_ENABLE_INDICATE = b"\x02\x00"


def hex_bytes(value: bytes | None) -> str:
    if not value:
        return "-"
    return value.hex(" ")


def short_hex(value: bytes | None, length: int = 8) -> str:
    if not value:
        return "-"
    return value[:length].hex(" ")


@dataclass
class Session:
    source: Path
    start_frame: int
    cccd_frame: int
    writes_48: list[bytes] = field(default_factory=list)
    inds_20: list[bytes] = field(default_factory=list)
    all_writes: list[bytes] = field(default_factory=list)
    all_inds: list[bytes] = field(default_factory=list)

    @property
    def challenge(self) -> bytes | None:
        return self.inds_20[0] if len(self.inds_20) >= 1 else None

    @property
    def auth_response(self) -> bytes | None:
        return self.writes_48[0] if len(self.writes_48) >= 1 else None

    @property
    def auth_confirm(self) -> bytes | None:
        return self.inds_20[1] if len(self.inds_20) >= 2 else None

    @property
    def state_request(self) -> bytes | None:
        return self.writes_48[1] if len(self.writes_48) >= 2 else None

    @property
    def state_indication(self) -> bytes | None:
        return self.inds_20[2] if len(self.inds_20) >= 3 else None

    @property
    def has_min_flow(self) -> bool:
        return (
            self.challenge is not None
            and self.auth_response is not None
            and self.auth_confirm is not None
            and self.state_request is not None
            and self.state_indication is not None
        )


def _sorted_events(path: Path):
    events = parse_btsnoop(path)
    return sorted(events, key=lambda e: (e["ts"], e["frame"]))


def extract_sessions(path: Path) -> list[Session]:
    events = _sorted_events(path)
    sessions: list[Session] = []
    current: Session | None = None

    for event in events:
        if not (event.get("is_write") or event.get("is_notify")):
            continue

        handle = event.get("handle")
        value = event.get("value", b"")

        is_cccd_enable = (
            event.get("is_write")
            and handle == HANDLE_CCCD
            and value == CCCD_ENABLE_INDICATE
        )
        if is_cccd_enable:
            current = Session(
                source=path,
                start_frame=event["frame"],
                cccd_frame=event["frame"],
            )
            sessions.append(current)
            continue

        if current is None:
            continue

        if event.get("is_write") and handle == HANDLE_WRITE:
            current.all_writes.append(value)
            if len(value) == 48:
                current.writes_48.append(value)

        if event.get("is_notify") and handle == HANDLE_INDICATE:
            current.all_inds.append(value)
            if len(value) == 20:
                current.inds_20.append(value)

    return sessions


def common_prefix_len(values: Iterable[bytes]) -> int:
    values = list(values)
    if not values:
        return 0
    shortest = min(len(v) for v in values)
    for index in range(shortest):
        byte = values[0][index]
        if any(v[index] != byte for v in values[1:]):
            return index
    return shortest


def summarize_sessions(sessions: list[Session], show_raw: bool = False) -> None:
    print(f"Total sessions: {len(sessions)}")
    full_flow = [session for session in sessions if session.has_min_flow]
    print(f"Sessions with full 6-step flow: {len(full_flow)}")
    print()

    for index, session in enumerate(sessions, start=1):
        print(
            f"[{index}] {session.source.name} "
            f"cccd_frame={session.cccd_frame} "
            f"writes48={len(session.writes_48)} inds20={len(session.inds_20)} "
            f"full_flow={session.has_min_flow}"
        )
        print(f"    challenge      : {short_hex(session.challenge)}")
        print(f"    auth_response  : {short_hex(session.auth_response)}")
        print(f"    auth_confirm   : {short_hex(session.auth_confirm)}")
        print(f"    state_request  : {short_hex(session.state_request)}")
        print(f"    state_indicate : {short_hex(session.state_indication)}")
        if show_raw:
            print(f"    challenge(raw)      : {hex_bytes(session.challenge)}")
            print(f"    auth_response(raw)  : {hex_bytes(session.auth_response)}")
            print(f"    auth_confirm(raw)   : {hex_bytes(session.auth_confirm)}")
            print(f"    state_request(raw)  : {hex_bytes(session.state_request)}")
            print(f"    state_indicate(raw) : {hex_bytes(session.state_indication)}")
        print()

    if full_flow:
        challenge_values = [session.challenge for session in full_flow if session.challenge]
        auth_values = [session.auth_response for session in full_flow if session.auth_response]
        state_req_values = [session.state_request for session in full_flow if session.state_request]
        state_values = [session.state_indication for session in full_flow if session.state_indication]

        print("Cross-session stats (full-flow only):")
        print(f"  challenge unique count   : {len(set(challenge_values))}")
        print(f"  auth_response unique     : {len(set(auth_values))}")
        print(f"  state_request unique     : {len(set(state_req_values))}")
        print(f"  state_indication unique  : {len(set(state_values))}")
        print(f"  challenge common prefix  : {common_prefix_len(challenge_values)} bytes")
        print(f"  auth_response prefix     : {common_prefix_len(auth_values)} bytes")
        print(f"  state_request prefix     : {common_prefix_len(state_req_values)} bytes")
        print(f"  state_indication prefix  : {common_prefix_len(state_values)} bytes")
        print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="One or more btsnoop_hci.log files",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="Print full hex for extracted step payloads",
    )
    args = parser.parse_args()

    all_sessions: list[Session] = []
    for path in args.paths:
        sessions = extract_sessions(path)
        all_sessions.extend(sessions)

    summarize_sessions(all_sessions, show_raw=args.show_raw)

    write_lengths = Counter()
    indicate_lengths = Counter()
    for session in all_sessions:
        write_lengths.update(len(value) for value in session.all_writes)
        indicate_lengths.update(len(value) for value in session.all_inds)

    if all_sessions:
        print("Length histograms across extracted sessions:")
        print(f"  write lengths    : {dict(sorted(write_lengths.items()))}")
        print(f"  indicate lengths : {dict(sorted(indicate_lengths.items()))}")


if __name__ == "__main__":
    main()
