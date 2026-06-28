#!/usr/bin/env python3
"""Extract crypto-relevant clues from Ninja APK/native library.

This script is fully static (no root/device needed) and focuses on:
- JNI exports related to BLE crypto/session handling
- strings that mention pairing/session/encrypt/decrypt
- algorithm hints (AES/GCM/Poly1305/ChaCha/etc.)

Usage example:
  python3 tools/extract_apk_crypto_clues.py \
    --apk ~/Downloads/ninja_extracted/com.sharkninja.ninja.connected.kitchen.apk \
    --so ~/Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


JNI_FILTER = re.compile(
    r"ext(Encrypt|Decrypt|DecryptDataWithOptionalKey|EncryptDataWithOptionalKey|"
    r"ProcessBTData|SendBTPayload|SetRequestCallback|GetMac)",
    re.IGNORECASE,
)

HIGH_VALUE_STRING_PATTERNS = [
    r"PAIRING DEBUG",
    r"sessionID|session id|session parameters|set session",
    r"encrypt|decrypt|cipher|nonce|iv|auth tag|authentication tag",
    r"No near device with uuid to (encrypt|decrypt|set session id)",
    r"Parsed session ID from encrypted packet",
    r"GET_GrillState|GET_ProbeState|GET_CookState",
    r"SetCookCommand|SET_Cook_Command|SET_GrillPower",
    r"BtAppPayload|BtGrillCommand|bt_data_type",
]


def run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except FileNotFoundError:
        return ""


def first_existing_tool(names: list[str]) -> str | None:
    for name in names:
        if shutil.which(name):
            return name
    return None


def extract_jni_exports(so_path: Path) -> list[str]:
    nm_tool = first_existing_tool(["nm", "llvm-nm", "gnm"])
    if not nm_tool:
        return []
    output = run_command([nm_tool, "-D", str(so_path)])
    exports = []
    for line in output.splitlines():
        if JNI_FILTER.search(line):
            exports.append(line.strip())
    return exports


def extract_strings(so_path: Path) -> list[str]:
    output = run_command(["strings", str(so_path)])
    return output.splitlines()


def select_high_value_lines(lines: list[str]) -> list[str]:
    selected: list[str] = []
    for line in lines:
        if len(line) > 240:
            continue
        for pattern in HIGH_VALUE_STRING_PATTERNS:
            if re.search(pattern, line, flags=re.IGNORECASE):
                selected.append(line)
                break
    unique = []
    seen = set()
    for line in selected:
        if line not in seen:
            unique.append(line)
            seen.add(line)
    return unique


def detect_algorithm_hints(lines: list[str]) -> dict[str, int]:
    hint_patterns = {
        "aes": r"\baes\b",
        "gcm": r"\bgcm\b|authentication tag",
        "poly1305": r"poly1305",
        "chacha": r"chacha",
        "ctr": r"\bctr\b",
        "cbc": r"\bcbc\b",
        "nonce": r"\bnonce\b",
        "iv": r"\biv\b",
        "session": r"session",
    }
    counts: dict[str, int] = {key: 0 for key in hint_patterns}
    for line in lines:
        low = line.lower()
        for key, pattern in hint_patterns.items():
            if re.search(pattern, low):
                counts[key] += 1
    return counts


def print_report(apk_path: Path, so_path: Path) -> None:
    print("=== Ninja APK crypto clue report ===")
    print(f"APK: {apk_path}")
    print(f"SO : {so_path}")
    print()

    if not apk_path.exists():
        print("[!] APK path not found")
    if not so_path.exists():
        print("[!] SO path not found")
    if not apk_path.exists() or not so_path.exists():
        return

    file_output = run_command(["file", str(so_path)]).strip()
    if file_output:
        print("Native library info:")
        print(f"  {file_output}")
        print()

    exports = extract_jni_exports(so_path)
    print(f"JNI export matches ({len(exports)}):")
    for line in exports[:30]:
        print(f"  {line}")
    print()

    string_lines = extract_strings(so_path)
    high_value = select_high_value_lines(string_lines)
    print(f"High-value strings ({len(high_value)}):")
    for line in high_value[:120]:
        print(f"  {line}")
    if len(high_value) > 120:
        print(f"  ... ({len(high_value) - 120} more)")
    print()

    hints = detect_algorithm_hints(string_lines)
    print("Algorithm hint counts:")
    for key in sorted(hints):
        print(f"  {key:10s}: {hints[key]}")
    print()

    print("Assessment:")
    if hints.get("gcm", 0) > 0:
        print("  - AEAD-like clue detected (auth tag mismatch string present).")
    if hints.get("session", 0) > 0:
        print("  - Session-scoped crypto is strongly indicated.")
    if exports:
        print("  - JNI entrypoints for encrypt/decrypt/process/send are available for static RE.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apk",
        type=Path,
        default=Path.home() / "Downloads/ninja_extracted/com.sharkninja.ninja.connected.kitchen.apk",
        help="Path to official Ninja APK",
    )
    parser.add_argument(
        "--so",
        type=Path,
        default=Path.home() / "Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so",
        help="Path to libgrillcore_android.so",
    )
    args = parser.parse_args()
    print_report(args.apk, args.so)


if __name__ == "__main__":
    main()
