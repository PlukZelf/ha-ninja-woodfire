#!/usr/bin/env python3
"""Static ELF/AArch64 analysis of libgrillcore_android.so — no phone needed.

Parses sections, resolves runtime offsets (from our Frida captures) to file offsets,
disassembles with capstone, follows BL call chains, and searches .rodata for
plausible embedded AES keys (16/32 constant byte blocks referenced near crypto code).
"""
import os
import struct
import sys

# The proprietary .so is never committed (see CLAUDE.md) — place your own
# extracted copy at tools/artifacts/extracted/lib/arm64-v8a/ or override
# with the NINJA_SO_PATH environment variable.
PATH = os.environ.get(
    "NINJA_SO_PATH",
    os.path.join(
        os.path.dirname(__file__),
        "artifacts", "extracted", "lib", "arm64-v8a", "libgrillcore_android.so",
    ),
)

with open(PATH, "rb") as f:
    DATA = f.read()

# ---- ELF section header parsing ----
e_shoff = struct.unpack_from("<Q", DATA, 0x28)[0]
e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", DATA, 0x3a)


def sh(i):
    off = e_shoff + i * e_shentsize
    name, typ, flags, addr, offset, size, link, info, align, entsize = struct.unpack_from(
        "<IIQQQQIIQQ", DATA, off
    )
    return dict(
        name=name, type=typ, flags=flags, addr=addr, offset=offset,
        size=size, link=link, info=info, align=align, entsize=entsize,
    )


shstr = sh(e_shstrndx)
strtab_off = shstr["offset"]


def getname(nameoff):
    end = DATA.index(b"\x00", strtab_off + nameoff)
    return DATA[strtab_off + nameoff : end].decode()


SECTIONS = []
for i in range(e_shnum):
    s = sh(i)
    s["nm"] = getname(s["name"])
    SECTIONS.append(s)


def addr_to_off(addr):
    """Convert a runtime/vaddr (as seen in Frida, relative to module base) to a file offset."""
    for s in SECTIONS:
        if s["addr"] <= addr < s["addr"] + s["size"] and s["type"] != 8:  # skip NOBITS
            return s["offset"] + (addr - s["addr"])
    return None


def off_to_addr(off):
    for s in SECTIONS:
        if s["offset"] <= off < s["offset"] + s["size"] and s["type"] != 8:
            return s["addr"] + (off - s["offset"])
    return None


if __name__ == "__main__":
    print(f"[*] {PATH}: {len(DATA)} bytes, {e_shnum} sections\n")
    for s in SECTIONS:
        if s["size"] > 0:
            print(f"  {s['nm']:20} addr={s['addr']:#010x} off={s['offset']:#010x} size={s['size']:#010x} type={s['type']}")
