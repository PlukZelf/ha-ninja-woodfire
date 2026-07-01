#!/usr/bin/env python3
"""Parse .dynsym to get ground-truth vaddrs for our known JNI export names."""
import struct
from elf_analyze import DATA, SECTIONS

def find_section(name):
    for s in SECTIONS:
        if s["nm"] == name:
            return s
    return None

dynsym = find_section(".dynsym")
dynstr = find_section(".dynstr")

# Elf64_Sym: st_name(4) st_info(1) st_other(1) st_shndx(2) st_value(8) st_size(8) = 24 bytes
SYM_SIZE = 24
n = dynsym["size"] // SYM_SIZE

TARGETS = [
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptDataWithOptionalKey",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptDataWithOptionalKey",
    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSendBTPayload",
    "JNI_OnLoad",
]

found = {}
for i in range(n):
    off = dynsym["offset"] + i * SYM_SIZE
    st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", DATA, off)
    end = DATA.index(b"\x00", dynstr["offset"] + st_name)
    name = DATA[dynstr["offset"] + st_name : end].decode(errors="replace")
    if name in TARGETS:
        found[name] = (st_value, st_size, st_shndx)

print(f"[*] .dynsym has {n} entries\n")
for t in TARGETS:
    if t in found:
        v, sz, shndx = found[t]
        print(f"  {t}\n    vaddr={v:#010x}  size={sz}  shndx={shndx}")
    else:
        print(f"  {t}  -- NOT FOUND")

# Also just dump the first 20 exported (non-zero value) function-type symbols to sanity check ranges.
print("\n[*] sample of exported FUNC symbols (first 15 with STT_FUNC and value!=0):")
count = 0
for i in range(n):
    off = dynsym["offset"] + i * SYM_SIZE
    st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", DATA, off)
    stt = st_info & 0xf
    if stt == 2 and st_value != 0:  # STT_FUNC
        end = DATA.index(b"\x00", dynstr["offset"] + st_name)
        name = DATA[dynstr["offset"] + st_name : end].decode(errors="replace")
        print(f"    {st_value:#010x}  {name}")
        count += 1
        if count >= 15:
            break
