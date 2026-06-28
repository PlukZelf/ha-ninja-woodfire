#!/usr/bin/env python3
"""Rank likely core crypto callees from BT JNI entrypoints.

Static-only helper that:
1) locates JNI export start addresses via `nm -D`
2) disassembles short windows via `objdump`
3) extracts `bl 0x...` targets
4) ranks shared targets across encrypt/decrypt/process/send wrappers

The highest-frequency shared targets are usually closer to core logic.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


ENTRYPOINTS = [
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptDataWithOptionalKey",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptDataWithOptionalKey",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSendBTPayload",
]


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout


def find_tool(names: list[str]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def parse_nm_exports(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    pattern = re.compile(r"^([0-9a-fA-F]+)\s+\w\s+(\S+)$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        addr_hex, symbol = match.groups()
        if symbol in ENTRYPOINTS:
            result[symbol] = int(addr_hex, 16)
    return result


def disasm_window(objdump_tool: str, so_path: Path, start: int, window: int) -> str:
    stop = start + window
    return run(
        [
            objdump_tool,
            "-d",
            f"--start-address=0x{start:x}",
            f"--stop-address=0x{stop:x}",
            str(so_path),
        ]
    )


def extract_bl_targets(disasm: str) -> list[str]:
    targets = []
    pattern = re.compile(r"\bbl\s+0x([0-9a-fA-F]+)")
    for line in disasm.splitlines():
        match = pattern.search(line)
        if match:
            targets.append(f"0x{match.group(1).lower()}")
    return targets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--so",
        type=Path,
        default=Path.home() / "Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so",
    )
    parser.add_argument(
        "--window",
        type=lambda value: int(value, 0),
        default=0x180,
        help="bytes to disassemble from each entrypoint start",
    )
    args = parser.parse_args()

    nm_tool = find_tool(["nm", "llvm-nm", "gnm"])
    objdump_tool = find_tool(["objdump", "llvm-objdump", "gobjdump"])

    if not args.so.exists():
        raise SystemExit(f"SO not found: {args.so}")
    if not nm_tool or not objdump_tool:
        raise SystemExit("Missing required tool(s): nm/objdump")

    exports = parse_nm_exports(run([nm_tool, "-D", str(args.so)]))
    if not exports:
        raise SystemExit("No target exports found")

    by_entry: dict[str, list[str]] = {}
    for symbol in ENTRYPOINTS:
        address = exports.get(symbol)
        if address is None:
            continue
        disasm = disasm_window(objdump_tool, args.so, address, args.window)
        by_entry[symbol] = extract_bl_targets(disasm)

    target_counter = Counter()
    target_to_entries: dict[str, set[str]] = defaultdict(set)
    for entry, targets in by_entry.items():
        for target in set(targets):
            target_counter[target] += 1
            target_to_entries[target].add(entry)

    print("=== BTCore shared call-target ranking ===")
    print(f"SO: {args.so}")
    print(f"window: 0x{args.window:x}")
    print()

    for entry, targets in by_entry.items():
        unique = list(dict.fromkeys(targets))
        print(f"{entry}")
        print(f"  unique bl targets ({len(unique)}): {', '.join(unique[:12])}")
        if len(unique) > 12:
            print(f"  ... (+{len(unique) - 12} more)")
    print()

    print("Top shared targets (higher = better reverse priority):")
    for target, count in sorted(target_counter.items(), key=lambda item: (-item[1], item[0]))[:25]:
        entries = sorted(target_to_entries[target])
        print(f"  {target}  shared_by={count}  entries={len(entries)}")
    print()

    likely_core = [
        (target, count)
        for target, count in target_counter.items()
        if count >= 3
    ]
    likely_core.sort(key=lambda item: (-item[1], item[0]))

    print("Likely core candidates (shared_by >= 3):")
    if not likely_core:
        print("  none")
    for target, count in likely_core:
        print(f"  {target} (shared_by={count})")


if __name__ == "__main__":
    main()
