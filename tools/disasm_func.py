#!/usr/bin/env python3
"""Disassemble a function (by vaddr/size) with capstone, showing BL call targets
and any ADRP+ADD/LDR pairs (used to reference .rodata constants)."""
import sys
import capstone
from elf_analyze import DATA, addr_to_off, SECTIONS


def resolve_symbol_names():
    """Map vaddr -> symbol name from .dynsym, for annotating call targets."""
    import struct
    dynsym = next(s for s in SECTIONS if s["nm"] == ".dynsym")
    dynstr = next(s for s in SECTIONS if s["nm"] == ".dynstr")
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
        out[st_value] = name
    return out


SYMBOLS = resolve_symbol_names()


def disasm(vaddr, size, show=True):
    file_off = addr_to_off(vaddr)
    if file_off is None:
        print(f"[!] cannot resolve vaddr {vaddr:#x} to file offset")
        return [], []
    code = DATA[file_off : file_off + size]
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    md.detail = True
    calls = []
    lines = []
    adrp_reg = {}  # track ADRP target per register for ADRP+ADD/LDR const resolution
    for insn in md.disasm(code, vaddr):
        line = f"  {insn.address:#010x}  {insn.mnemonic:8} {insn.op_str}"
        lines.append((insn.address, insn.mnemonic, insn.op_str))
        if show:
            ann = ""
            if insn.mnemonic == "bl":
                try:
                    target = int(insn.op_str.lstrip("#"), 16)
                    name = SYMBOLS.get(target, "")
                    ann = f"    ; -> {name}" if name else "    ; -> (local/unnamed)"
                    calls.append(target)
                except ValueError:
                    pass
            print(line + ann)
    return lines, calls


if __name__ == "__main__":
    vaddr = int(sys.argv[1], 16)
    size = int(sys.argv[2])
    disasm(vaddr, size)
