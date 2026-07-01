#!/usr/bin/env python3
"""Check whether known GATT-decrypt AES round functions (found live via Frida)
are reachable from extProcessBTData's call graph, and if so, print the exact
call CHAIN (not just the set) from root to that function."""
import struct
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


SYMBOLS = resolve_symbol_names()
MD = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
MD.detail = True


def guess_func_size(vaddr):
    if vaddr in SYMBOLS:
        _, size = SYMBOLS[vaddr]
        if size > 0:
            return size
    return 4096


def get_calls(vaddr):
    off = addr_to_off(vaddr)
    if off is None:
        return []
    size = guess_func_size(vaddr)
    code = DATA[off : off + size]
    out = []
    for insn in MD.disasm(code, vaddr):
        if insn.mnemonic == "bl":
            try:
                out.append(int(insn.op_str.lstrip("#"), 16))
            except ValueError:
                pass
    return out


def find_path(root, targets, max_depth=8):
    """BFS, return dict target -> path (list of vaddrs from root to target inclusive)."""
    from collections import deque
    found = {}
    q = deque([(root, [root])])
    visited = {root}
    while q:
        cur, path = q.popleft()
        if len(path) > max_depth:
            continue
        if cur in targets and cur not in found:
            found[cur] = path
        for c in get_calls(cur):
            if c not in visited:
                visited.add(c)
                q.append((c, path + [c]))
    return found


if __name__ == "__main__":
    root_name = "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData"
    root = next(v for v, (n, s) in SYMBOLS.items() if n == root_name)

    # Known GATT-decrypt bitsliced AES round function addrs (from live Frida capture this session).
    gatt_round_fns = {0x113f44, 0x113ee0, 0x114154}

    print(f"[*] root: {root_name} @ {root:#x}")
    print(f"[*] checking reachability of GATT round fns: {[hex(x) for x in gatt_round_fns]}\n")

    paths = find_path(root, gatt_round_fns, max_depth=10)
    if not paths:
        print("[*] NONE of the GATT round functions are reachable from extProcessBTData.")
        print("[*] -> Advert path uses a DIFFERENT crypto implementation entirely.")
    else:
        for target, path in paths.items():
            name = SYMBOLS.get(target, (None, 0))[0]
            print(f"[*] REACHABLE: {target:#x} ({name}) via path:")
            for v in path:
                nm = SYMBOLS.get(v, (None, 0))[0]
                print(f"      {v:#x}" + (f"  ({nm})" if nm else ""))
            print()
