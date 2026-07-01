#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ghidra headless post-analysis script: decompile ONE specific function (by address)
and its callees, depth-limited. Used to drill into a specific candidate found via
manual review of the broader dump."""
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

# Runs inside Ghidra's Jython via analyzeHeadless -postScript; edit this path
# to point at YOUR tools/artifacts/ directory before running.
OUT_PATH = r"C:\Users\micro\Documents\Sander\ha-ninja-woodfire\tools\artifacts\ghidra_decompiled_primitive.txt"
# The inner primitive used by the keyed advert transform FUN_002309ac.
TARGET_ADDRS = ["00231934", "002315a0"]
MAX_FUNCS = 10

monitor = ConsoleTaskMonitor()
program = getCurrentProgram()
fm = program.getFunctionManager()
addrFactory = program.getAddressFactory()

decomp = DecompInterface()
decomp.openProgram(program)

roots = []
for TARGET_ADDR in TARGET_ADDRS:
    target_addr = addrFactory.getAddress(TARGET_ADDR)
    root = fm.getFunctionAt(target_addr)
    if root is None:
        root = fm.getFunctionContaining(target_addr)
    if root is None:
        print("[!] no function found at/near " + TARGET_ADDR)
    else:
        roots.append(root)

if not roots:
    print("[!] no root functions resolved")
else:
    visited = set()
    queue = list(roots)
    out_lines = []
    count = 0

    while queue and count < MAX_FUNCS:
        fn = queue.pop(0)
        key = fn.getEntryPoint().toString()
        if key in visited:
            continue
        visited.add(key)
        count += 1

        res = decomp.decompileFunction(fn, 60, monitor)
        if res.decompileCompleted():
            code = res.getDecompiledFunction().getC()
        else:
            code = "// DECOMPILE FAILED: " + str(res.getErrorMessage())

        out_lines.append("=" * 80)
        out_lines.append("FUNCTION: " + fn.getName() + " @ " + fn.getEntryPoint().toString())
        out_lines.append("=" * 80)
        out_lines.append(code)
        out_lines.append("")

        for called in fn.getCalledFunctions(monitor):
            if called.getEntryPoint().toString() not in visited:
                queue.append(called)

    with open(OUT_PATH, "w") as f:
        f.write("\n".join(out_lines))

    print("[*] wrote " + str(count) + " decompiled functions to " + OUT_PATH)

decomp.dispose()
