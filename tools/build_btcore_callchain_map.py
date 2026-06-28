#!/usr/bin/env python3
"""Build a static call-chain map for BTCore native functions.

Given one or more seed addresses, this script disassembles short windows from
`libgrillcore_android.so`, extracts `bl 0x...` targets, and expands recursively.
It helps prioritize likely core crypto/session functions without dynamic hooks.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path


BL_PATTERN = re.compile(r"\bbl\s+0x([0-9a-fA-F]+)")


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


def parse_hex_address(value: str) -> int:
    value = value.strip().lower()
    if value.startswith("0x"):
        return int(value, 16)
    return int(value, 16)


def disasm_window(objdump_tool: str, so_path: Path, address: int, window: int) -> str:
    stop = address + window
    return run(
        [
            objdump_tool,
            "-d",
            f"--start-address=0x{address:x}",
            f"--stop-address=0x{stop:x}",
            str(so_path),
        ]
    )


def extract_bl_targets(disasm: str) -> list[int]:
    targets: list[int] = []
    for line in disasm.splitlines():
        match = BL_PATTERN.search(line)
        if match:
            targets.append(int(match.group(1), 16))
    return targets


def build_graph(
    objdump_tool: str,
    so_path: Path,
    seeds: list[int],
    window: int,
    depth: int,
    max_nodes: int,
) -> tuple[dict[int, set[int]], set[int]]:
    edges: dict[int, set[int]] = defaultdict(set)
    visited: set[int] = set()
    queue = deque((seed, 0) for seed in seeds)

    while queue and len(visited) < max_nodes:
        node, level = queue.popleft()
        if node in visited:
            continue
        visited.add(node)

        disasm = disasm_window(objdump_tool, so_path, node, window)
        if not disasm:
            continue

        targets = extract_bl_targets(disasm)
        for target in targets:
            edges[node].add(target)
            if level < depth:
                queue.append((target, level + 1))

    return edges, visited


def format_hex(address: int) -> str:
    return f"0x{address:x}"


def print_summary(edges: dict[int, set[int]], seeds: list[int]) -> None:
    out_degree = Counter({node: len(targets) for node, targets in edges.items()})
    in_degree = Counter()
    for node, targets in edges.items():
        for target in targets:
            in_degree[target] += 1

    print("Seeds:")
    print("  " + ", ".join(format_hex(seed) for seed in seeds))
    print()

    print(f"Graph nodes with outgoing edges: {len(edges)}")
    print(f"Total directed edges: {sum(len(targets) for targets in edges.values())}")
    print()

    print("Top hubs by in-degree:")
    for address, degree in in_degree.most_common(15):
        print(f"  {format_hex(address):>12}  in={degree:2d} out={out_degree.get(address, 0):2d}")
    print()

    print("Top hubs by out-degree:")
    for address, degree in out_degree.most_common(15):
        print(f"  {format_hex(address):>12}  out={degree:2d} in={in_degree.get(address, 0):2d}")
    print()

    print("Seed expansions:")
    for seed in seeds:
        targets = sorted(edges.get(seed, set()))
        preview = ", ".join(format_hex(target) for target in targets[:12])
        suffix = f" ... (+{len(targets) - 12})" if len(targets) > 12 else ""
        print(f"  {format_hex(seed)} -> {preview}{suffix}")


def write_edge_list(path: Path, edges: dict[int, set[int]]) -> None:
    lines: list[str] = []
    for source in sorted(edges):
        for target in sorted(edges[source]):
            lines.append(f"{format_hex(source)},{format_hex(target)}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--so",
        type=Path,
        default=Path.home() / "Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        required=True,
        help="Seed addresses in hex, e.g. 0x155b94 0x160310",
    )
    parser.add_argument(
        "--window",
        type=lambda value: int(value, 0),
        default=0x140,
        help="Disassembly byte window per node",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Recursive expansion depth for BL targets",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=80,
        help="Safety cap for expanded graph nodes",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional CSV edge list output file",
    )
    args = parser.parse_args()

    objdump_tool = find_tool(["objdump", "llvm-objdump", "gobjdump"])
    if not objdump_tool:
        raise SystemExit("No objdump tool found")
    if not args.so.exists():
        raise SystemExit(f"SO not found: {args.so}")

    seeds = [parse_hex_address(seed) for seed in args.seeds]
    edges, visited = build_graph(
        objdump_tool=objdump_tool,
        so_path=args.so,
        seeds=seeds,
        window=args.window,
        depth=args.depth,
        max_nodes=args.max_nodes,
    )

    print("=== BTCore call-chain map ===")
    print(f"objdump: {objdump_tool}")
    print(f"so: {args.so}")
    print(f"window: 0x{args.window:x} depth: {args.depth} max_nodes: {args.max_nodes}")
    print(f"visited nodes: {len(visited)}")
    print()
    print_summary(edges, seeds)

    if args.out:
        write_edge_list(args.out, edges)
        print()
        print(f"Edge list written: {args.out}")


if __name__ == "__main__":
    main()
