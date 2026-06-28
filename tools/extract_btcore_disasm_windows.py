#!/usr/bin/env python3
"""Extract focused disassembly windows for key BT JNI exports.

This script is intended for static reverse engineering without Ghidra/Frida.
It uses `nm -D` and `objdump -d` to dump short instruction windows around
the JNI entrypoints we care about.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


TARGET_EXPORTS = [
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptDataWithOptionalKey",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptDataWithOptionalKey",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSendBTPayload",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSetRequestCallback",
]


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout


def find_tool(candidates: list[str]) -> str | None:
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def parse_exports(nm_output: str) -> dict[str, int]:
    exports: dict[str, int] = {}
    pattern = re.compile(r"^([0-9a-fA-F]+)\s+\w\s+(\S+)$")
    for line in nm_output.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        address_hex, symbol = match.groups()
        if symbol in TARGET_EXPORTS:
            exports[symbol] = int(address_hex, 16)
    return exports


def extract_bl_targets(disassembly: str) -> list[str]:
    targets = []
    pattern = re.compile(r"\bbl\s+0x([0-9a-fA-F]+)")
    for line in disassembly.splitlines():
        match = pattern.search(line)
        if match:
            targets.append(f"0x{match.group(1).lower()}")
    unique = []
    seen = set()
    for target in targets:
        if target not in seen:
            unique.append(target)
            seen.add(target)
    return unique


def disasm_window(objdump: str, so_path: Path, address: int, window: int) -> str:
    start = max(0, address)
    stop = address + window
    return run_command(
        [
            objdump,
            "-d",
            f"--start-address=0x{start:x}",
            f"--stop-address=0x{stop:x}",
            str(so_path),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--so",
        type=Path,
        default=Path.home() / "Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so",
        help="Path to libgrillcore_android.so",
    )
    parser.add_argument(
        "--window",
        type=lambda value: int(value, 0),
        default=0x180,
        help="Instruction byte window from each function start (default: 0x180)",
    )
    args = parser.parse_args()

    nm_tool = find_tool(["nm", "llvm-nm", "gnm"])
    objdump_tool = find_tool(["objdump", "llvm-objdump", "gobjdump"])

    if not args.so.exists():
        raise SystemExit(f"SO not found: {args.so}")
    if not nm_tool:
        raise SystemExit("No nm tool found")
    if not objdump_tool:
        raise SystemExit("No objdump tool found")

    nm_output = run_command([nm_tool, "-D", str(args.so)])
    exports = parse_exports(nm_output)

    print("=== BTCore disassembly windows ===")
    print(f"SO: {args.so}")
    print(f"nm: {nm_tool}")
    print(f"objdump: {objdump_tool}")
    print(f"window: 0x{args.window:x}")
    print()

    for symbol in TARGET_EXPORTS:
        address = exports.get(symbol)
        if address is None:
            print(f"--- {symbol}\nmissing in nm -D output\n")
            continue

        print(f"--- {symbol}")
        print(f"start: 0x{address:x}")
        disassembly = disasm_window(objdump_tool, args.so, address, args.window)
        if not disassembly:
            print("disassembly failed\n")
            continue

        bl_targets = extract_bl_targets(disassembly)
        print(f"bl targets ({len(bl_targets)}): {', '.join(bl_targets[:16])}")
        if len(bl_targets) > 16:
            print(f"... (+{len(bl_targets) - 16} more)")
        print("snippet:")

        lines = disassembly.splitlines()
        for line in lines[:30]:
            print(line)
        print()


if __name__ == "__main__":
    main()
