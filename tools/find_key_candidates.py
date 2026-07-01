#!/usr/bin/env python3
"""Automated static-analysis pass: walk the call graph from extProcessBTData,
flag candidate embedded key constants in .rodata, and report only the
suspicious spots (not full disassembly).

Heuristic for "candidate key constant":
  - An ADRP+ADD (or ADRP+LDR) pair computes an absolute address A into .rodata
  - The bytes at A (16 or 32 bytes) have LOW printable-ASCII ratio (i.e. look
    like binary/random data, not a string or another pointer table)
  - We report every such reference found while walking the call graph,
    grouped by target address, with hit count and which functions reference it.

Fully offline. Reads the CORRECT .so (pulled from device this session):
  tools/artifacts/extracted/lib/arm64-v8a/libgrillcore_android.so
"""
import struct
import sys
import capstone
from elf_analyze import DATA, addr_to_off, SECTIONS


def find_section(name):
    return next(s for s in SECTIONS if s["nm"] == name)


def resolve_symbol_names():
    dynsym = find_section(".dynsym")
    dynstr = find_section(".dynstr")
    SYM_SIZE = 24
    n = dynsym["size"] // SYM_SIZE
    out = {}
    for i in range(n):
        off = dynsym["offset"] + i * SYM_SIZE
        st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", DATA, off)
        if st_value == 0:
            continue
        end = DATA.index(b"\x00", dynstr["offset"] + st_name)
        name = DATA[dynstr["offset"] + st_name : end].decode(errors="replace")
        out[st_value] = (name, st_size)
    return out


SYMBOLS = resolve_symbol_names()  # vaddr -> (name, size)
RODATA = find_section(".rodata")
TEXT = find_section(".text")

MD = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
MD.detail = True


def bytes_at(vaddr, n):
    off = addr_to_off(vaddr)
    if off is None:
        return None
    return DATA[off : off + n]


def printable_ratio(b):
    if not b:
        return 0.0
    good = sum(1 for c in b if 0x20 <= c < 0x7f)
    return good / len(b)


def guess_func_size(vaddr):
    """If vaddr is an exported symbol, use its size. Else guess via next known symbol
    or a generous cap (we just need enough bytes to disassemble sanely)."""
    if vaddr in SYMBOLS:
        _, size = SYMBOLS[vaddr]
        if size > 0:
            return size
    # Fallback: scan forward for a plausible function end (ret without further
    # immediate call fan-out) capped at 4KB — good enough for a heuristic pass.
    return 4096


def disasm_function(vaddr, size):
    off = addr_to_off(vaddr)
    if off is None:
        return []
    code = DATA[off : off + size]
    return list(MD.disasm(code, vaddr))


def analyze_function(vaddr, visited, candidates, calls_out, depth, max_depth):
    if vaddr in visited or depth > max_depth:
        return
    visited.add(vaddr)
    size = guess_func_size(vaddr)
    insns = disasm_function(vaddr, size)

    adrp_val = {}  # reg -> page value
    for insn in insns:
        if insn.mnemonic == "adrp" and len(insn.operands) == 2:
            reg = insn.reg_name(insn.operands[0].reg)
            imm = insn.operands[1].imm
            adrp_val[reg] = imm
        elif insn.mnemonic in ("add",) and len(insn.operands) == 3:
            dst = insn.reg_name(insn.operands[0].reg)
            src = insn.reg_name(insn.operands[1].reg)
            if adrp_val.get(src) is not None and insn.operands[2].type == capstone.arm64_const.ARM64_OP_IMM:
                addr = adrp_val[src] + insn.operands[2].imm
                check_candidate(addr, vaddr, insn.address, candidates)
                adrp_val[dst] = None  # now holds an absolute addr, not a page — stop chaining
        elif insn.mnemonic in ("ldr", "ldur") and len(insn.operands) == 2:
            # ldr Xd, [Xn, #imm] where Xn came from adrp -> another rodata ref pattern
            if insn.operands[1].type == capstone.arm64_const.ARM64_OP_MEM:
                base = insn.reg_name(insn.operands[1].mem.base)
                if base in adrp_val and adrp_val[base] is not None:
                    addr = adrp_val[base] + insn.operands[1].mem.disp
                    check_candidate(addr, vaddr, insn.address, candidates)
        elif insn.mnemonic == "bl":
            try:
                target = int(insn.op_str.lstrip("#"), 16)
                calls_out.setdefault(vaddr, []).append(target)
                analyze_function(target, visited, candidates, calls_out, depth + 1, max_depth)
            except ValueError:
                pass


def check_candidate(addr, from_func, from_insn, candidates):
    if not (RODATA["addr"] <= addr < RODATA["addr"] + RODATA["size"]):
        return
    for sz in (16, 32):
        b = bytes_at(addr, sz)
        if b is None or len(b) < sz:
            continue
        pr = printable_ratio(b)
        if pr < 0.4:  # looks binary, not a string
            key = (addr, sz)
            candidates.setdefault(key, {"hex": b.hex(), "refs": []})
            candidates[key]["refs"].append((from_func, from_insn))


def main():
    root_name = "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData"
    root_vaddr = next(v for v, (n, s) in SYMBOLS.items() if n == root_name)
    print(f"[*] root: {root_name} @ {root_vaddr:#x}\n")

    visited = set()
    candidates = {}
    calls = {}
    analyze_function(root_vaddr, visited, candidates, calls, depth=0, max_depth=6)

    print(f"[*] visited {len(visited)} functions, found {len(candidates)} candidate constants\n")

    # Sort candidates by number of references (more refs = more "load-bearing")
    ranked = sorted(candidates.items(), key=lambda kv: -len(kv[1]["refs"]))
    for (addr, sz), info in ranked[:40]:
        names = []
        for (ffrom, finsn) in info["refs"][:3]:
            nm = SYMBOLS.get(ffrom, (None, 0))[0]
            names.append(f"{ffrom:#x}{'(' + nm + ')' if nm else ''}@{finsn:#x}")
        print(f"  addr={addr:#010x} size={sz:2d}  hex={info['hex']}")
        print(f"    refs({len(info['refs'])}): {', '.join(names)}")
    print(f"\n[*] {len(visited)} functions visited (call graph depth-limited to 6).")


if __name__ == "__main__":
    main()
