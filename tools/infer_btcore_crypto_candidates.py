#!/usr/bin/env python3
"""Infer likely BTCore crypto core functions from JNI wrapper call patterns.

Approach:
1) Disassemble fixed windows for encrypt/decrypt JNI entrypoints
2) Extract direct `bl` call targets
3) Separate shared plumbing calls from asymmetric crypto calls
4) Rank candidate addresses for deeper reverse-engineering
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


ENTRYPOINTS = {
    "decrypt": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData",
    "decrypt_opt": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptDataWithOptionalKey",
    "encrypt": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData",
    "encrypt_opt": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptDataWithOptionalKey",
    "process": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData",
    "send": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSendBTPayload",
}

BL_PATTERN = re.compile(r"\bbl\s+0x([0-9a-fA-F]+)")
NM_PATTERN = re.compile(r"^([0-9a-fA-F]+)\s+\w\s+(\S+)$")


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout


def find_tool(candidates: list[str]) -> str | None:
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def parse_exports(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    wanted = set(ENTRYPOINTS.values())
    for line in text.splitlines():
        match = NM_PATTERN.match(line.strip())
        if not match:
            continue
        address_hex, symbol = match.groups()
        if symbol in wanted:
            result[symbol] = int(address_hex, 16)
    return result


def disasm_window(objdump_tool: str, so_path: Path, address: int, window: int) -> str:
    return run(
        [
            objdump_tool,
            "-d",
            f"--start-address=0x{address:x}",
            f"--stop-address=0x{address + window:x}",
            str(so_path),
        ]
    )


def extract_targets(disasm: str) -> set[int]:
    targets: set[int] = set()
    for line in disasm.splitlines():
        match = BL_PATTERN.search(line)
        if match:
            targets.add(int(match.group(1), 16))
    return targets


def fmt(addresses: set[int]) -> str:
    return ", ".join(f"0x{value:x}" for value in sorted(addresses)) if addresses else "-"


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
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional output file for textual report",
    )
    args = parser.parse_args()

    nm_tool = find_tool(["nm", "llvm-nm", "gnm"])
    objdump_tool = find_tool(["objdump", "llvm-objdump", "gobjdump"])
    if not nm_tool or not objdump_tool:
        raise SystemExit("Missing required tools nm/objdump")
    if not args.so.exists():
        raise SystemExit(f"SO not found: {args.so}")

    exports = parse_exports(run([nm_tool, "-D", str(args.so)]))
    key_to_targets: dict[str, set[int]] = {}
    missing: list[str] = []

    for key, symbol in ENTRYPOINTS.items():
        address = exports.get(symbol)
        if address is None:
            missing.append(symbol)
            continue
        disasm = disasm_window(objdump_tool, args.so, address, args.window)
        key_to_targets[key] = extract_targets(disasm)

    decrypt = key_to_targets.get("decrypt", set())
    decrypt_opt = key_to_targets.get("decrypt_opt", set())
    encrypt = key_to_targets.get("encrypt", set())
    encrypt_opt = key_to_targets.get("encrypt_opt", set())
    process = key_to_targets.get("process", set())
    send = key_to_targets.get("send", set())

    shared_enc_dec = (encrypt & decrypt) | (encrypt_opt & decrypt_opt)
    all_four = encrypt & decrypt & encrypt_opt & decrypt_opt
    enc_only = (encrypt | encrypt_opt) - (decrypt | decrypt_opt)
    dec_only = (decrypt | decrypt_opt) - (encrypt | encrypt_opt)

    transport_plumbing = shared_enc_dec & (process | send)
    likely_crypto_core = (shared_enc_dec - transport_plumbing)
    likely_encrypt_branch = enc_only
    likely_decrypt_branch = dec_only

    lines: list[str] = []
    lines.append("=== BTCore crypto candidate inference ===")
    lines.append(f"SO: {args.so}")
    lines.append(f"window: 0x{args.window:x}")
    if missing:
        lines.append(f"missing exports: {len(missing)}")
        for symbol in missing:
            lines.append(f"  - {symbol}")
    lines.append("")

    for key in ["decrypt", "decrypt_opt", "encrypt", "encrypt_opt", "process", "send"]:
        targets = key_to_targets.get(key, set())
        lines.append(f"{key:11s}: {len(targets):2d} targets")
        lines.append(f"  {fmt(targets)}")
    lines.append("")

    lines.append(f"shared_enc_dec ({len(shared_enc_dec)}): {fmt(shared_enc_dec)}")
    lines.append(f"all_four       ({len(all_four)}): {fmt(all_four)}")
    lines.append(f"enc_only       ({len(enc_only)}): {fmt(enc_only)}")
    lines.append(f"dec_only       ({len(dec_only)}): {fmt(dec_only)}")
    lines.append("")

    lines.append("Likely buckets:")
    lines.append(f"  crypto_core_candidates ({len(likely_crypto_core)}): {fmt(likely_crypto_core)}")
    lines.append(f"  encrypt_branch_only    ({len(likely_encrypt_branch)}): {fmt(likely_encrypt_branch)}")
    lines.append(f"  decrypt_branch_only    ({len(likely_decrypt_branch)}): {fmt(likely_decrypt_branch)}")

    prioritized = sorted(likely_crypto_core | likely_encrypt_branch | likely_decrypt_branch)
    lines.append("")
    lines.append("Prioritized next targets:")
    for address in prioritized:
        lines.append(f"  - 0x{address:x}")

    report = "\n".join(lines) + "\n"
    print(report, end="")

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Report written: {args.out}")


if __name__ == "__main__":
    main()
