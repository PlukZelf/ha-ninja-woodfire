#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ghidra headless post-analysis script (Jython, runs INSIDE Ghidra).
Decompiles extProcessBTData and recursively decompiles its callees (depth-limited),
writing readable C-like pseudocode to a text file for offline review.

Run via analyzeHeadless with -postScript pointing at this file.
"""
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor

OUT_PATH = r"C:\Users\micro\Documents\Sander\ha-ninja-woodfire\tools\artifacts\ghidra_decompiled_advert.txt"
ROOT_SYMBOL = "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData"
MAX_FUNCS = 60

monitor = ConsoleTaskMonitor()
program = getCurrentProgram()
fm = program.getFunctionManager()
symtab = program.getSymbolTable()

decomp = DecompInterface()
decomp.openProgram(program)

def find_function_by_name(name):
    for sym in symtab.getSymbols(name):
        fn = fm.getFunctionAt(sym.getAddress())
        if fn:
            return fn
    return None

root = find_function_by_name(ROOT_SYMBOL)
if root is None:
    print("[!] root function not found: " + ROOT_SYMBOL)
else:
    visited = set()
    queue = [root]
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

        # enqueue callees
        for called in fn.getCalledFunctions(monitor):
            if called.getEntryPoint().toString() not in visited:
                queue.append(called)

    with open(OUT_PATH, "w") as f:
        f.write("\n".join(out_lines))

    print("[*] wrote " + str(count) + " decompiled functions to " + OUT_PATH)

decomp.dispose()
