"""
AArch64 Unicorn emulation oracle for libgrillcore_android.so.

Loads the ARM64 Android shared library inside Unicorn, satisfies all 133
bionic/libc imports via Python hook handlers, and exposes encrypt_data /
decrypt_data / process_bt_data behind the same API as GrillCoreNative.

Works on any host architecture (x86-64 dev machines, ARM64 HA hosts).
Requires: unicorn>=2.0, pyelftools>=0.29

Usage::

    from .grillcore_emu import GrillCoreEmulator
    emu = GrillCoreEmulator("/path/to/libgrillcore_android.so")
    if emu.load():
        ct = emu.encrypt_data(b"hello world", "device-uuid")
        pt = emu.decrypt_data(ct, "device-uuid")
"""

from __future__ import annotations

import logging
import math
import os
import struct
import time
from pathlib import Path
from typing import Optional

_LOGGER = logging.getLogger(__name__)

try:
    from unicorn import (
        Uc, UC_ARCH_ARM64, UC_MODE_ARM,
        UC_HOOK_CODE, UC_HOOK_MEM_INVALID,
        UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC, UC_PROT_ALL, UC_PROT_NONE,
        UC_MEM_WRITE_UNMAPPED, UC_MEM_READ_UNMAPPED, UC_MEM_FETCH_UNMAPPED,
        UC_MEM_WRITE_PROT, UC_MEM_FETCH_PROT,
        UcError,
    )
    from unicorn.arm64_const import (
        UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
        UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X7,
        UC_ARM64_REG_X8, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC,
        UC_ARM64_REG_TPIDR_EL0,
    )
    from elftools.elf.elffile import ELFFile
    from elftools.elf.relocation import RelocationSection
    _HAVE_DEPS = True
except ImportError as _e:
    _HAVE_DEPS = False
    _LOGGER.debug("grillcore_emu dependencies unavailable: %s", _e)

# ---------------------------------------------------------------------------
# Memory layout  (all sizes page-aligned to 0x1000)
# ---------------------------------------------------------------------------
_PAGE       = 0x1000

BASE        = 0x00100000   # .so loaded here; vaddr 0 maps to BASE
SO_MSIZE    = 0x00500000   # 5 MB covers full virtual extent of the .so

UTIL_BASE   = 0x00700000   # errno slot, misc 4-byte data
UTIL_SIZE   = 0x00001000
SENTINEL    = UTIL_BASE    # emu_start(until=SENTINEL) stops emulation

TRAMP_BASE  = 0x00800000   # one NOP (4 bytes) per imported symbol
TRAMP_SIZE  = 0x00010000   # 64 KB = 16384 slots — plenty of headroom

STACK_BASE  = 0x01000000
STACK_SIZE  = 0x00200000   # 2 MB
STACK_TOP   = STACK_BASE + STACK_SIZE - 16

HEAP_BASE   = 0x02000000
HEAP_SIZE   = 0x00800000   # 8 MB

JNI_BASE    = 0x03000000   # JNIEnv struct + function table
JNI_SIZE    = 0x00002000

TLS_BASE    = 0x04000000   # pthread TLS backing
TLS_SIZE    = 0x00001000

# AArch64 relocation type numbers
_R_AARCH64_ABS64     = 257
_R_AARCH64_GLOB_DAT  = 1025
_R_AARCH64_JUMP_SLOT = 1026
_R_AARCH64_RELATIVE  = 1027

# JNI 1.6 function table indices (0-based into JNINativeInterface array)
_JNI_IDX: dict[str, int] = {
    "GetVersion":               4,
    "FindClass":                6,
    "ExceptionClear":          17,
    "DeleteLocalRef":          23,
    "GetMethodID":             33,
    "CallObjectMethod":        36,
    "NewStringUTF":           167,
    "GetStringUTFChars":      169,
    "ReleaseStringUTFChars":  170,
    "GetArrayLength":         171,
    "NewByteArray":           186,
    "GetByteArrayElements":   188,
    "ReleaseByteArrayElements": 192,
    "GetByteArrayRegion":     200,
    "SetByteArrayRegion":     208,
    "ExceptionCheck":         228,
    "GetObjectClass":          31,
    "IsInstanceOf":            32,
}
_JNI_TABLE_ENTRIES = 232   # total entries in JNINativeInterface (JNI 1.6)


# ---------------------------------------------------------------------------
class _AbortError(RuntimeError):
    """Raised when emulated code calls abort()."""


# Bump-pointer heap
# ---------------------------------------------------------------------------

class _Heap:
    def __init__(self, uc: "Uc", base: int, size: int) -> None:
        self._uc = uc
        self._base = base
        self._ptr = base
        self._end = base + size

    def _alloc(self, n: int) -> int:
        n = max(8, (n + 15) & ~15)
        if self._ptr + n > self._end:
            raise MemoryError(f"emulated heap exhausted ({n} bytes requested)")
        addr = self._ptr
        self._ptr += n
        self._uc.mem_write(addr, b"\x00" * n)
        return addr

    # --- generic helpers ---
    def write_bytes(self, data: bytes) -> int:
        addr = self._alloc(len(data) or 8)
        if data:
            self._uc.mem_write(addr, data)
        return addr

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self._uc.mem_read(addr, n))

    # --- JNI byte array: [u32 length][bytes] ---
    def new_byte_array(self, data: bytes) -> int:
        addr = self._alloc(4 + len(data) + 8)
        self._uc.mem_write(addr, struct.pack("<I", len(data)))
        if data:
            self._uc.mem_write(addr + 4, data)
        return addr

    def byte_array_len(self, handle: int) -> int:
        return struct.unpack_from("<I", self.read(handle, 4))[0]

    def byte_array_data_ptr(self, handle: int) -> int:
        return handle + 4

    def read_byte_array(self, handle: int) -> bytes:
        n = self.byte_array_len(handle)
        return self.read(handle + 4, n) if n else b""

    # --- JNI string: [u32 len_without_nul][null-terminated UTF-8] ---
    def new_string_utf(self, s: str) -> int:
        encoded = s.encode("utf-8")
        addr = self._alloc(4 + len(encoded) + 1 + 8)
        self._uc.mem_write(addr, struct.pack("<I", len(encoded)))
        self._uc.mem_write(addr + 4, encoded + b"\x00")
        return addr

    def string_data_ptr(self, handle: int) -> int:
        return handle + 4

    def read_c_string(self, ptr: int, maxlen: int = 4096) -> str:
        try:
            raw = bytes(self._uc.mem_read(ptr, maxlen))
        except Exception:
            return ""
        end = raw.find(b"\x00")
        return raw[:end].decode("utf-8", errors="replace") if end >= 0 else raw.decode("utf-8", errors="replace")

    # --- plain C string ---
    def write_c_string(self, s: str) -> int:
        encoded = s.encode("utf-8") + b"\x00"
        return self.write_bytes(encoded)

    # --- malloc/free passthrough ---
    def malloc(self, n: int) -> int:
        return self._alloc(n)

    def free(self, _addr: int) -> None:
        pass  # bump allocator; GC not needed for short-lived encrypt/decrypt calls


# ---------------------------------------------------------------------------
# TLS (pthread key / specific)
# ---------------------------------------------------------------------------

class _TLS:
    def __init__(self) -> None:
        self._next_key = 1
        self._data: dict[int, int] = {}

    def key_create(self) -> int:
        k = self._next_key
        self._next_key += 1
        self._data[k] = 0
        return k

    def get(self, key: int) -> int:
        return self._data.get(key, 0)

    def set(self, key: int, val: int) -> None:
        self._data[key] = val


# ---------------------------------------------------------------------------
# Main emulator
# ---------------------------------------------------------------------------

class GrillCoreEmulator:
    """
    Unicorn-based emulation oracle for libgrillcore_android.so.

    Public API mirrors GrillCoreNative so coordinator.py can swap between them.
    """

    def __init__(self, lib_path: "Path | str" = "") -> None:
        self._lib_path = Path(lib_path) if lib_path else _default_lib_path()
        self._uc: Optional["Uc"] = None
        self._heap: Optional[_Heap] = None
        self._tls = _TLS()
        self._sym_addr: dict[str, int] = {}     # export name → BASE + vaddr
        self._tramp_by_addr: dict[int, str] = {}  # trampoline addr → sym name
        self._tramp_by_name: dict[str, int] = {}  # sym name → trampoline addr
        self._jni_env: int = 0                  # address to pass as x0
        self._errno_slot: int = 0               # address of errno int
        # Optional deterministic-entropy replay: when non-empty, getrandom()
        # consumes from this buffer instead of os.urandom().  Used to reproduce
        # the app-side randomness of a captured BLE pairing session so the
        # derived AES key matches the real device session.
        self._random_queue: bytearray = bytearray()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_random_replay(self, data: bytes) -> None:
        """Queue bytes for getrandom() to return (FIFO).  Empties → os.urandom."""
        self._random_queue = bytearray(data)

    def _next_random(self, n: int) -> bytes:
        """Return n bytes: from the replay queue if available, else os.urandom."""
        if len(self._random_queue) >= n:
            out = bytes(self._random_queue[:n])
            del self._random_queue[:n]
            return out
        if self._random_queue:
            _LOGGER.warning(
                "grillcore_emu: random replay queue exhausted (need %d, have %d) "
                "— falling back to os.urandom", n, len(self._random_queue))
            self._random_queue.clear()
        return os.urandom(n)

    def available(self) -> bool:
        return self._uc is not None

    def load(self) -> bool:
        """Load the .so into Unicorn.  Returns True on success."""
        if not _HAVE_DEPS:
            _LOGGER.warning(
                "grillcore_emu: 'unicorn' and/or 'pyelftools' not installed. "
                "Install with: pip install unicorn pyelftools"
            )
            return False
        if not self._lib_path.exists():
            _LOGGER.warning("grillcore_emu: .so not found at %s", self._lib_path)
            return False
        try:
            self._setup()
            _LOGGER.info("grillcore_emu: loaded %s", self._lib_path.name)
            return True
        except Exception as exc:
            _LOGGER.error("grillcore_emu: load failed: %s", exc, exc_info=True)
            self._uc = None
            return False

    def encrypt_data(self, payload: bytes, uuid: str) -> Optional[bytes]:
        """Encrypt a BLE payload for the given device UUID."""
        return self._jni_call("extEncryptData", payload, uuid)

    def decrypt_data(self, payload: bytes, uuid: str) -> Optional[bytes]:
        """Decrypt a BLE payload for the given device UUID."""
        return self._jni_call("extDecryptData", payload, uuid)

    def decrypt_data_with_key(self, payload: bytes, uuid: str, key: bytes) -> Optional[bytes]:
        """Decrypt using an explicit key (bypasses session registry)."""
        return self._jni_call("extDecryptDataWithOptionalKey", payload, uuid, key)

    def encrypt_data_with_key(self, payload: bytes, uuid: str, key: bytes) -> Optional[bytes]:
        """Encrypt using an explicit key."""
        return self._jni_call("extEncryptDataWithOptionalKey", payload, uuid, key)

    def process_bt_data(self, payload: bytes, uuid: str,
                        msg_type: int = 0) -> Optional[bytes]:
        """Feed raw BLE data through the native state machine.

        NOTE: extProcessBTData's JNI signature is (data: ByteArray, uuid: String,
        type: Int) -- a different argument order than encrypt/decrypt, plus a
        third 'type' int that selects how the packet is routed.  Returns the
        bytes the app should send back (e.g. the next handshake write), or None.
        """
        return self._jni_call_process_bt(payload, uuid, msg_type)

    def decode_advert(self, raw_advert: bytes) -> Optional[bytes]:
        """Decode a raw ~62-byte BLE advertisement into its plaintext 43-byte
        bit-packed buffer, by driving the real .so's internal whitening+AES
        transform (FUN_00230460) directly -- no reimplementation of the
        bitsliced fixslice AES or the checksum/whitening preprocessing needed.

        The raw advert contains two manufacturer-data AD structures (company
        0x0C4F): a 20-byte payload at offset 0xb and a 23-byte payload at
        offset 0x27 (see docs/... and REBOOT notes for the AD-structure
        layout). FUN_00230460 must be called ONCE PER HALF -- it validates
        the input length is in range 0x11..0x1f (17-31) and hard-errors
        outside that range, so the two halves cannot be concatenated first.

        Returns the concatenated 43-byte plaintext, or None if either half
        failed to decode (e.g. wrong length, or the emulator isn't loaded).
        """
        if not self._uc:
            return None
        if len(raw_advert) < 0x27 + 23:
            _LOGGER.debug("grillcore_emu: advert too short for decode_advert: %d", len(raw_advert))
            return None

        half1 = raw_advert[0x0B:0x0B + 20]
        half2 = raw_advert[0x27:0x27 + 23]

        decoded1 = self._decode_advert_half(half1)
        decoded2 = self._decode_advert_half(half2)
        if decoded1 is None or decoded2 is None:
            return None
        return decoded1 + decoded2

    def _decode_advert_half(self, raw_half: bytes) -> Optional[bytes]:
        """Call FUN_00230460(out, {word0,ptr,len}) on a single 17-31 byte
        AD-structure payload half. Returns the decoded bytes, or None on
        error (the native function signals failure via a {0,1,0} sentinel
        struct instead of raising)."""
        # NOTE: this is the RAW vaddr, used directly (NOT BASE + offset) --
        # empirically verified: BASE+0x230460 produces garbage/failure, plain
        # 0x230460 reproduces the byte-verified decode (see tools/
        # check_base_offset2.py). The loader apparently places PT_LOAD
        # segments at their raw p_vaddr, and BASE is just the low end of the
        # reserved mapping region, not an additive relocation slide.
        FUN_00230460 = 0x230460
        heap = self._heap
        assert heap is not None

        data_ptr = heap.write_bytes(raw_half)
        param_ptr = heap.malloc(24)
        self._uc.mem_write(
            param_ptr,
            (0).to_bytes(8, "little")
            + data_ptr.to_bytes(8, "little")
            + len(raw_half).to_bytes(8, "little"),
        )
        out_ptr = heap.malloc(24)
        self._uc.mem_write(out_ptr, b"\x00" * 24)

        self._call(FUN_00230460, [out_ptr, param_ptr])

        out_bytes = self._uc.mem_read(out_ptr, 24)
        ptr = int.from_bytes(out_bytes[8:16], "little")
        length = int.from_bytes(out_bytes[16:24], "little")
        if length == 0 or length > 4096 or not ptr:
            _LOGGER.debug(
                "grillcore_emu: decode_advert half failed (len=%d ptr=%#x)", length, ptr
            )
            return None
        return bytes(self._uc.mem_read(ptr, length))

    # ------------------------------------------------------------------
    # Internal setup
    # ------------------------------------------------------------------

    def _setup(self) -> None:
        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self._uc = uc

        # Map all regions
        uc.mem_map(BASE,       SO_MSIZE,   UC_PROT_ALL)
        uc.mem_map(UTIL_BASE,  UTIL_SIZE,  UC_PROT_ALL)
        uc.mem_map(TRAMP_BASE, TRAMP_SIZE, UC_PROT_ALL)
        uc.mem_map(STACK_BASE, STACK_SIZE, UC_PROT_ALL)
        uc.mem_map(HEAP_BASE,  HEAP_SIZE,  UC_PROT_ALL)
        uc.mem_map(JNI_BASE,   JNI_SIZE,   UC_PROT_ALL)
        uc.mem_map(TLS_BASE,   TLS_SIZE,   UC_PROT_ALL)

        # Fill trampolines with NOP (0xD503201F) so any stray fetch is harmless
        uc.mem_write(TRAMP_BASE, b"\x1f\x20\x03\xd5" * (TRAMP_SIZE // 4))

        self._heap = _Heap(uc, HEAP_BASE, HEAP_SIZE)
        self._errno_slot = UTIL_BASE + 8  # 4-byte errno value

        # Load ELF
        self._load_elf()

        # Build JNI env
        self._build_jni_env()

        # Install hooks
        uc.hook_add(UC_HOOK_CODE, self._hook_code,
                    begin=TRAMP_BASE, end=TRAMP_BASE + TRAMP_SIZE - 1)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._hook_mem_invalid)

        # Patch emulation-specific panics:
        # 1. parking_lot "is_unlocked" assertion at 0x3e2c80: noreturn panic handler
        #    "returns" in emulation (catch-all trampoline), leaving a non-zero state.
        # 2. Direct abort-wrapper call at 0x3c4050 (inside the extEncryptData path).
        # 3. Abort-wrapper itself at 0x3e2da4 (dead code after noreturn panic).
        # Replacing each with NOP avoids aborting while still letting normal paths run.
        NOP = b"\x1f\x20\x03\xd5"
        for fva in (0x3e2c80, 0x3c4050, 0x3e2da4):
            uc.mem_write(BASE + fva, NOP)

        # Run INIT_ARRAY constructors
        self._run_init_array()

        # Call GrillCoreSDK.init so the "not initialized" guard passes
        self._sdk_init()

    def _load_elf(self) -> None:
        uc = self._uc
        assert uc is not None
        data = self._lib_path.read_bytes()
        elf = ELFFile(self._lib_path.open("rb"))

        # --- 1. Map PT_LOAD segments ---
        for seg in elf.iter_segments():
            h = seg.header
            if h.p_type != "PT_LOAD":
                continue
            vaddr = BASE + h.p_vaddr
            filesz = h.p_filesz
            raw = data[h.p_offset: h.p_offset + filesz]
            uc.mem_write(vaddr, raw)

        # --- 2. Collect exported symbols ---
        dynsym = elf.get_section_by_name(".dynsym")
        syms = list(dynsym.iter_symbols())
        by_name: dict[str, int] = {}
        for s in syms:
            if s.entry.st_value and s.entry.st_info.type == "STT_FUNC" and s.entry.st_shndx != "SHN_UNDEF":
                by_name[s.name] = BASE + (s.entry.st_value & ~1)
        self._sym_addr = by_name

        # --- 3. Assign trampolines to undefined (imported) symbols ---
        tramp_idx = 0
        sym_to_tramp: dict[str, int] = {}
        for s in syms:
            if s.entry.st_shndx == "SHN_UNDEF" and s.name:
                if s.name not in sym_to_tramp:
                    taddr = TRAMP_BASE + tramp_idx * 4
                    sym_to_tramp[s.name] = taddr
                    self._tramp_by_addr[taddr] = s.name
                    self._tramp_by_name[s.name] = taddr
                    tramp_idx += 1
        _LOGGER.debug("grillcore_emu: %d imports trampolined", tramp_idx)

        # --- 4. Apply relocations ---
        for sec in elf.iter_sections():
            if not isinstance(sec, RelocationSection):
                continue
            for rel in sec.iter_relocations():
                off = BASE + rel.entry.r_offset
                rtype = rel.entry.r_info_type
                sym_idx = rel.entry.r_info >> 32
                sym_name = syms[sym_idx].name if sym_idx < len(syms) else ""
                addend = getattr(rel.entry, "r_addend", 0)

                if rtype == _R_AARCH64_RELATIVE:
                    val = BASE + addend
                    uc.mem_write(off, struct.pack("<Q", val))

                elif rtype in (_R_AARCH64_GLOB_DAT, _R_AARCH64_JUMP_SLOT, _R_AARCH64_ABS64):
                    if sym_name in sym_to_tramp:
                        val = sym_to_tramp[sym_name]
                    elif sym_name in by_name:
                        val = by_name[sym_name]
                    else:
                        val = 0
                    uc.mem_write(off, struct.pack("<Q", val))

    def _build_jni_env(self) -> None:
        """Build JNIEnv + function table in emulated memory, assign trampolines."""
        uc = self._uc
        assert uc is not None

        # Memory layout:
        #   JNI_BASE + 0   : ENV_STRUCT (8 bytes) = pointer to FN_TABLE
        #   JNI_BASE + 8   : FN_TABLE (232 * 8 bytes)
        ENV_STRUCT = JNI_BASE
        FN_TABLE   = JNI_BASE + 8

        # Assign a trampoline to each JNI method we handle
        jni_tramp: dict[str, int] = {}
        noop_tramp: int = TRAMP_BASE + 499 * 4  # dedicated noop slot (slot 499)

        for name, idx in _JNI_IDX.items():
            # JNI slots 200..428 — safely above libc slots 0..132, below noop 499
            slot = 200 + idx
            taddr = TRAMP_BASE + slot * 4
            jni_tramp[name] = taddr
            self._tramp_by_addr[taddr] = f"jni::{name}"
            self._tramp_by_name[f"jni::{name}"] = taddr

        # Write function table: default all entries to noop_tramp
        table_bytes = struct.pack("<Q", noop_tramp) * _JNI_TABLE_ENTRIES
        table_arr = bytearray(table_bytes)
        for name, idx in _JNI_IDX.items():
            taddr = jni_tramp[name]
            struct.pack_into("<Q", table_arr, idx * 8, taddr)
        uc.mem_write(FN_TABLE, bytes(table_arr))

        # ENV_STRUCT points to FN_TABLE
        uc.mem_write(ENV_STRUCT, struct.pack("<Q", FN_TABLE))

        self._jni_env = ENV_STRUCT  # pass this as x0

    def _run_init_array(self) -> None:
        """Run DT_INIT_ARRAY constructors (Rust static initialisers)."""
        uc = self._uc
        assert uc is not None
        elf = ELFFile(self._lib_path.open("rb"))
        dyn = elf.get_section_by_name(".dynamic")
        init_arr = init_sz = 0
        for tag in dyn.iter_tags():
            if tag.entry.d_tag == "DT_INIT_ARRAY":
                init_arr = BASE + tag.entry.d_val
            if tag.entry.d_tag == "DT_INIT_ARRAYSZ":
                init_sz = tag.entry.d_val
        if not init_arr or not init_sz:
            return
        for i in range(0, init_sz, 8):
            raw = bytes(uc.mem_read(init_arr + i, 8))
            ptr = struct.unpack_from("<Q", raw)[0]
            if ptr and ptr != BASE:  # skip null/0 entries
                _LOGGER.debug("grillcore_emu: INIT_ARRAY[%d] = %#x", i // 8, ptr)
                self._call(ptr, [])

    def _sdk_init(self) -> None:
        """Call GrillCoreSDK.init so the 'not initialized' guard passes."""
        sym = "Java_com_sharkninja_grillcore_GrillCoreSDK_00024Companion_init"
        addr = self._sym_addr.get(sym)
        if not addr:
            _LOGGER.warning("grillcore_emu: SDK init symbol not found")
            return
        _LOGGER.debug("grillcore_emu: calling SDK init @ %#x", addr)
        heap = self._heap
        # Build minimal args: env, companion-this (0), app-context (0),
        # empty string args (apiKey, baseUrl, socketUrl, region)
        env = self._jni_env
        empty_str = heap.new_string_utf("")
        # Signature: init(env, obj, context, apiKey, baseUrl, socketUrl, region, ...)
        # Pass 0 for context (null) and empty strings for the rest
        args = [env, 0, 0, empty_str, empty_str, empty_str, empty_str, 0]
        try:
            self._call(addr, args, timeout_ms=10000)
            _LOGGER.debug("grillcore_emu: SDK init returned OK")
        except Exception as exc:
            _LOGGER.warning("grillcore_emu: SDK init raised %s — continuing anyway", exc)

    # ------------------------------------------------------------------
    # Unicorn call helper
    # ------------------------------------------------------------------

    def _call(self, addr: int, args: list[int], timeout_ms: int = 5000) -> int:
        """Call emulated function at addr with integer args (x0-x7), return x0."""
        uc = self._uc
        assert uc is not None

        # Set argument registers
        regs = [
            UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
            UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X7,
        ]
        for i, val in enumerate(args[:8]):
            uc.reg_write(regs[i], val & 0xFFFFFFFFFFFFFFFF)
        for i in range(len(args), 8):
            uc.reg_write(regs[i], 0)

        uc.reg_write(UC_ARM64_REG_SP, STACK_TOP)
        uc.reg_write(UC_ARM64_REG_X30, SENTINEL)  # LR = stop address

        # TPIDR_EL0: thread-local storage pointer (Rust uses this for panic info)
        uc.reg_write(UC_ARM64_REG_TPIDR_EL0, TLS_BASE)

        try:
            uc.emu_start(addr, SENTINEL, timeout=timeout_ms * 1000)
        except UcError as exc:
            pc = uc.reg_read(UC_ARM64_REG_PC)
            _LOGGER.debug(
                "grillcore_emu: emu_start error @ %#x: %s  (stopped at PC=%#x fva=%#x)",
                addr, exc, pc, pc - BASE,
            )

        return uc.reg_read(UC_ARM64_REG_X0)

    # ------------------------------------------------------------------
    # Hook dispatchers
    # ------------------------------------------------------------------

    def _hook_code(self, uc: "Uc", address: int, size: int, user_data: object) -> None:
        name = self._tramp_by_addr.get(address)
        if name is None:
            # Any other address in the trampoline region: unknown call — log, return 0, redirect
            if TRAMP_BASE <= address < TRAMP_BASE + TRAMP_SIZE:
                _LOGGER.debug("grillcore_emu: unknown trampoline @ %#x", address)
                uc.reg_write(UC_ARM64_REG_X0, 0)
                lr = uc.reg_read(UC_ARM64_REG_X30)
                uc.reg_write(UC_ARM64_REG_PC, lr)
            return
        if name.startswith("jni::"):
            self._dispatch_jni(uc, name[5:])
        else:
            self._dispatch_libc(uc, name)
        # Return: write PC = LR so the NOP at tramp addr is skipped
        lr = uc.reg_read(UC_ARM64_REG_X30)
        uc.reg_write(UC_ARM64_REG_PC, lr)

    def _hook_mem_invalid(self, uc: "Uc", access: int, address: int,
                          size: int, value: int, user_data: object) -> bool:
        pc = uc.reg_read(UC_ARM64_REG_PC)
        lr = uc.reg_read(UC_ARM64_REG_X30)
        x0 = uc.reg_read(UC_ARM64_REG_X0)
        _LOGGER.warning(
            "grillcore_emu: INVALID MEM access type=%d addr=%#x size=%d  PC=%#x(fva=%#x) LR=%#x x0=%#x",
            access, address, size, pc, pc - BASE, lr, x0,
        )
        return False  # let Unicorn raise the error

    # ------------------------------------------------------------------
    # JNI hook dispatch
    # ------------------------------------------------------------------

    def _dispatch_jni(self, uc: "Uc", name: str) -> None:
        heap = self._heap
        assert heap is not None
        x = lambda r: uc.reg_read(r)

        def ret(v: int) -> None:
            uc.reg_write(UC_ARM64_REG_X0, v & 0xFFFFFFFFFFFFFFFF)

        # env = x0, args start at x1 for JNI (x1 = this/obj, x2 onwards = real args)
        if name == "GetVersion":
            ret(0x00010006)  # JNI 1.6

        elif name == "NewByteArray":
            # (env, size)
            size = x(UC_ARM64_REG_X1)
            handle = heap.new_byte_array(b"\x00" * size)
            ret(handle)

        elif name == "SetByteArrayRegion":
            # (env, array, start, len, buf_ptr)
            arr   = x(UC_ARM64_REG_X1)
            start = x(UC_ARM64_REG_X2)
            length= x(UC_ARM64_REG_X3)
            buf   = x(UC_ARM64_REG_X4)
            if arr and length:
                data = bytes(uc.mem_read(buf, length))
                dest = heap.byte_array_data_ptr(arr) + start
                uc.mem_write(dest, data)

        elif name == "GetByteArrayElements":
            # (env, array, isCopy_ptr) → ptr to bytes
            arr    = x(UC_ARM64_REG_X1)
            is_copy = x(UC_ARM64_REG_X2)
            if is_copy:
                uc.mem_write(is_copy, b"\x00")  # JNI_FALSE
            ret(heap.byte_array_data_ptr(arr) if arr else 0)

        elif name == "ReleaseByteArrayElements":
            pass  # no-op

        elif name == "GetByteArrayRegion":
            # (env, array, start, len, buf)
            arr    = x(UC_ARM64_REG_X1)
            start  = x(UC_ARM64_REG_X2)
            length = x(UC_ARM64_REG_X3)
            buf    = x(UC_ARM64_REG_X4)
            if arr and length and buf:
                src = heap.byte_array_data_ptr(arr) + start
                data = bytes(uc.mem_read(src, length))
                uc.mem_write(buf, data)
            # returns void → no ret value needed

        elif name == "GetObjectClass":
            ret(0x1)  # dummy class ref

        elif name == "IsInstanceOf":
            ret(1)  # JNI_TRUE

        elif name == "GetArrayLength":
            # (env, array) → int
            arr = x(UC_ARM64_REG_X1)
            ret(heap.byte_array_len(arr) if arr else 0)

        elif name == "NewStringUTF":
            # (env, char* s) → jstring
            ptr = x(UC_ARM64_REG_X1)
            s = heap.read_c_string(ptr) if ptr else ""
            handle = heap.new_string_utf(s)
            ret(handle)

        elif name == "GetStringUTFChars":
            # (env, jstring, isCopy*) → const char*
            js     = x(UC_ARM64_REG_X1)
            is_copy = x(UC_ARM64_REG_X2)
            if is_copy:
                uc.mem_write(is_copy, b"\x00")
            ret(heap.string_data_ptr(js) if js else 0)

        elif name == "ReleaseStringUTFChars":
            pass

        elif name == "GetMethodID":
            # return non-null dummy so callers don't error
            ret(0x1)

        elif name == "FindClass":
            ret(0x1)

        elif name == "CallObjectMethod":
            # return NULL (no Java object to emulate)
            ret(0)

        elif name == "DeleteLocalRef":
            pass

        elif name == "ExceptionCheck":
            ret(0)  # JNI_FALSE

        elif name == "ExceptionClear":
            pass

        else:
            _LOGGER.debug("grillcore_emu: unhandled JNI::%s", name)
            ret(0)

    # ------------------------------------------------------------------
    # libc / bionic hook dispatch
    # ------------------------------------------------------------------

    def _dispatch_libc(self, uc: "Uc", name: str) -> None:  # noqa: C901
        heap = self._heap
        assert heap is not None
        x = lambda r: uc.reg_read(r)

        def ret(v: int) -> None:
            uc.reg_write(UC_ARM64_REG_X0, v & 0xFFFFFFFFFFFFFFFF)

        def rdf(addr: int, n: int) -> bytes:
            try:
                return bytes(uc.mem_read(addr, n))
            except UcError:
                return b"\x00" * n

        def wrt(addr: int, data: bytes) -> None:
            uc.mem_write(addr, data)

        def ru32(addr: int) -> int:
            return struct.unpack_from("<I", rdf(addr, 4))[0]

        def ri64(addr: int) -> int:
            v = struct.unpack_from("<Q", rdf(addr, 8))[0]
            return v if v < 0x8000000000000000 else v - 0x10000000000000000

        # --- memory ---
        if name == "malloc":
            n = x(UC_ARM64_REG_X0)
            ret(heap.malloc(n) if n else 0)

        elif name == "calloc":
            nmemb = x(UC_ARM64_REG_X0); size = x(UC_ARM64_REG_X1)
            addr = heap.malloc(nmemb * size)
            ret(addr)

        elif name == "realloc":
            _ptr = x(UC_ARM64_REG_X0); n = x(UC_ARM64_REG_X1)
            # bump allocator: just malloc new and copy if old ptr valid
            new_addr = heap.malloc(n)
            if _ptr and n:
                old_data = rdf(_ptr, min(n, 4096))
                wrt(new_addr, old_data[:n])
            ret(new_addr)

        elif name in ("free", "cfree"):
            heap.free(x(UC_ARM64_REG_X0))

        elif name == "posix_memalign":
            memptr = x(UC_ARM64_REG_X0)
            align  = x(UC_ARM64_REG_X1)
            size   = x(UC_ARM64_REG_X2)
            a = heap.malloc(size + align)
            a = (a + align - 1) & ~(align - 1)
            wrt(memptr, struct.pack("<Q", a))
            ret(0)

        # --- string/memory ops ---
        elif name in ("memset", "__memset_chk"):
            dst = x(UC_ARM64_REG_X0); c = x(UC_ARM64_REG_X1) & 0xFF; n = x(UC_ARM64_REG_X2)
            if dst and n:
                wrt(dst, bytes([c]) * n)
            ret(dst)

        elif name in ("memcpy", "__memcpy_chk", "memmove", "__memmove_chk", "bcopy"):
            dst = x(UC_ARM64_REG_X0); src = x(UC_ARM64_REG_X1); n = x(UC_ARM64_REG_X2)
            if dst and src and n:
                wrt(dst, rdf(src, n))
            ret(dst)

        elif name == "memcmp":
            p1 = x(UC_ARM64_REG_X0); p2 = x(UC_ARM64_REG_X1); n = x(UC_ARM64_REG_X2)
            if not p1 or not p2 or not n:
                ret(0); return
            a = rdf(p1, n); b = rdf(p2, n)
            ret(0 if a == b else (1 if a > b else -1 & 0xFFFFFFFFFFFFFFFF))

        elif name == "memchr":
            ptr = x(UC_ARM64_REG_X0); c = x(UC_ARM64_REG_X1) & 0xFF; n = x(UC_ARM64_REG_X2)
            if not ptr or not n:
                ret(0); return
            data = rdf(ptr, n)
            idx = data.find(bytes([c]))
            ret(ptr + idx if idx >= 0 else 0)

        elif name == "strlen":
            ptr = x(UC_ARM64_REG_X0)
            if not ptr:
                ret(0); return
            # Read in 256-byte chunks to avoid crossing unmapped pages
            length = 0
            while True:
                chunk = rdf(ptr + length, 256)
                nul = chunk.find(b"\x00")
                if nul >= 0:
                    ret(length + nul); break
                length += 256
                if length > 65536:
                    ret(65536); break

        elif name in ("strcmp", "strcasecmp"):
            p1 = x(UC_ARM64_REG_X0); p2 = x(UC_ARM64_REG_X1)
            if not p1 or not p2:
                ret(0); return
            a = heap.read_c_string(p1); b = heap.read_c_string(p2)
            ret(0 if a == b else (1 if a > b else -1 & 0xFFFFFFFFFFFFFFFF))

        elif name in ("strncmp", "strncasecmp"):
            p1 = x(UC_ARM64_REG_X0); p2 = x(UC_ARM64_REG_X1); n = x(UC_ARM64_REG_X2)
            if not p1 or not p2:
                ret(0); return
            a = rdf(p1, n); b = rdf(p2, n)
            ret(0 if a == b else (1 if a > b else -1 & 0xFFFFFFFFFFFFFFFF))

        elif name == "strchr":
            ptr = x(UC_ARM64_REG_X0); c = x(UC_ARM64_REG_X1) & 0xFF
            if not ptr:
                ret(0); return
            data = rdf(ptr, 4096)
            idx = data.find(bytes([c]))
            ret(ptr + idx if idx >= 0 else 0)

        elif name == "strrchr":
            ptr = x(UC_ARM64_REG_X0); c = x(UC_ARM64_REG_X1) & 0xFF
            if not ptr:
                ret(0); return
            data = rdf(ptr, 4096)
            idx = data.rfind(bytes([c]))
            ret(ptr + idx if idx >= 0 else 0)

        elif name in ("strcat", "strncat"):
            dst = x(UC_ARM64_REG_X0); src = x(UC_ARM64_REG_X1)
            ret(dst)

        elif name in ("strcpy", "strncpy"):
            dst = x(UC_ARM64_REG_X0); src = x(UC_ARM64_REG_X1)
            n = x(UC_ARM64_REG_X2) if name == "strncpy" else 4096
            if dst and src:
                data = rdf(src, n)
                end = data.find(b"\x00")
                copy = data[:end + 1] if end >= 0 else data
                wrt(dst, copy)
            ret(dst)

        elif name in ("strerror", "strerror_r"):
            # strerror_r(errno, buf, buflen)
            buf = x(UC_ARM64_REG_X1); buflen = x(UC_ARM64_REG_X2)
            msg = b"error\x00"
            if buf and buflen:
                wrt(buf, msg[:buflen])
                ret(buf)
            else:
                s = heap.write_c_string("error")
                ret(s)

        elif name in ("snprintf", "vsnprintf", "sprintf", "vsprintf",
                      "printf", "fprintf", "dprintf",
                      "puts", "fputs", "fputc", "putchar", "fwrite",
                      "fflush", "fread"):
            # Logging/output: silently succeed
            ret(0)

        elif name in ("atoi", "atol", "atoll"):
            ptr = x(UC_ARM64_REG_X0)
            if ptr:
                s = heap.read_c_string(ptr)
                try:
                    ret(int(s.strip()))
                except ValueError:
                    ret(0)
            else:
                ret(0)

        elif name in ("strtod", "strtof", "strtol", "strtoll", "strtoul", "strtoull"):
            ret(0)

        # --- bionic specifics ---
        elif name == "__android_log_write":
            # (prio, tag, text) → no-op, return 1
            ret(1)

        elif name == "__android_log_print":
            ret(1)

        elif name == "__system_property_get":
            # (name, value) → write empty string, return 0
            val_ptr = x(UC_ARM64_REG_X1)
            if val_ptr:
                wrt(val_ptr, b"\x00")
            ret(0)

        elif name == "__assert2":
            file_ptr = x(UC_ARM64_REG_X0); line = x(UC_ARM64_REG_X1)
            fn_ptr = x(UC_ARM64_REG_X2); msg_ptr = x(UC_ARM64_REG_X3)
            msg = heap.read_c_string(msg_ptr) if msg_ptr else "?"
            raise AssertionError(f"emulated __assert2: {msg} (line {line})")

        elif name == "abort":
            # Raise so _sdk_init/_call can catch it; HA callers get None back gracefully
            lr = uc.reg_read(UC_ARM64_REG_X30)
            raise _AbortError(f"abort() at LR={lr:#x} (fva={lr - BASE:#x})")

        elif name == "__errno":
            # returns pointer to errno
            ret(self._errno_slot)

        elif name in ("__cxa_atexit", "__cxa_finalize", "__register_atfork"):
            ret(0)

        elif name == "__sF":
            # bionic stdio FILE array — just return a dummy non-null pointer
            ret(UTIL_BASE + 16)

        # --- entropy ---
        elif name == "getrandom":
            buf = x(UC_ARM64_REG_X0); n = x(UC_ARM64_REG_X1)
            if buf and n:
                wrt(buf, self._next_random(n))
            ret(n)

        elif name == "rand":
            import random
            ret(random.randint(0, 0x7FFFFFFF))

        elif name == "srand":
            pass

        # --- time ---
        elif name == "clock_gettime":
            tp = x(UC_ARM64_REG_X1)
            if tp:
                t = time.time()
                sec = int(t); nsec = int((t - sec) * 1e9)
                wrt(tp, struct.pack("<qq", sec, nsec))
            ret(0)

        elif name == "gettimeofday":
            tv = x(UC_ARM64_REG_X0)
            if tv:
                t = time.time()
                sec = int(t); usec = int((t - sec) * 1e6)
                wrt(tv, struct.pack("<qq", sec, usec))
            ret(0)

        elif name in ("nanosleep", "usleep", "sleep"):
            ret(0)  # don't actually sleep

        elif name in ("localtime_r", "localtime"):
            ret(0)

        # --- process / threading ---
        elif name == "getpid":
            ret(os.getpid())

        elif name == "gettid":
            ret(1)  # fake TID

        elif name == "sched_yield":
            ret(0)

        elif name == "sched_getaffinity":
            cpuset = x(UC_ARM64_REG_X2); size = x(UC_ARM64_REG_X1)
            if cpuset and size:
                wrt(cpuset, b"\x01" + b"\x00" * (size - 1))  # CPU 0 only
            ret(0)

        elif name == "prctl":
            ret(0)

        elif name == "getenv":
            ret(0)  # env vars not available

        elif name == "getcwd":
            buf = x(UC_ARM64_REG_X0); size = x(UC_ARM64_REG_X1)
            cwd = b"/\x00"
            if buf and size:
                wrt(buf, cwd[:size])
                ret(buf)
            else:
                ret(heap.write_bytes(cwd))

        elif name == "getauxval":
            # AT_PAGESZ=6 → 4096, rest → 0
            typ = x(UC_ARM64_REG_X0)
            ret(4096 if typ == 6 else 0)

        elif name == "syscall":
            # Unrecognised syscalls → return -1
            ret(0xFFFFFFFFFFFFFFFF)

        # --- pthread ---
        elif name == "pthread_key_create":
            key_ptr = x(UC_ARM64_REG_X0)
            key = self._tls.key_create()
            if key_ptr:
                wrt(key_ptr, struct.pack("<I", key))
            ret(0)

        elif name == "pthread_key_delete":
            ret(0)

        elif name == "pthread_getspecific":
            key = x(UC_ARM64_REG_X0)
            ret(self._tls.get(key))

        elif name == "pthread_setspecific":
            key = x(UC_ARM64_REG_X0); val = x(UC_ARM64_REG_X1)
            self._tls.set(key, val)
            ret(0)

        elif name == "pthread_once":
            # (once_ctrl, init_routine) - run routine if not done
            ctrl = x(UC_ARM64_REG_X0); func = x(UC_ARM64_REG_X1)
            done = ru32(ctrl) if ctrl else 1
            if not done:
                wrt(ctrl, struct.pack("<I", 1))
                if func:
                    self._call(func, [])
            ret(0)

        elif name == "pthread_create":
            # Don't actually spawn a thread — stub success, don't run thread_func
            # If init absolutely needs threads, we can run the function synchronously
            thread_ptr = x(UC_ARM64_REG_X0)
            if thread_ptr:
                wrt(thread_ptr, struct.pack("<Q", 0x1234))  # fake thread handle
            _LOGGER.debug("grillcore_emu: pthread_create stubbed (not executed)")
            ret(0)

        elif name in ("pthread_join", "pthread_detach"):
            ret(0)

        elif name in (
            "pthread_mutex_init", "pthread_mutex_lock", "pthread_mutex_unlock",
            "pthread_mutex_destroy", "pthread_mutex_trylock",
            "pthread_rwlock_rdlock", "pthread_rwlock_wrlock", "pthread_rwlock_unlock",
            "pthread_rwlock_init", "pthread_rwlock_destroy",
            "pthread_condattr_init", "pthread_condattr_destroy", "pthread_condattr_setclock",
            "pthread_cond_init", "pthread_cond_destroy",
            "pthread_cond_signal", "pthread_cond_broadcast",
            "pthread_cond_wait", "pthread_cond_timedwait",
            "pthread_attr_init", "pthread_attr_destroy",
            "pthread_attr_setstacksize", "pthread_attr_setdetachstate",
        ):
            ret(0)

        # --- file I/O (stubbed, should not be needed for crypto path) ---
        elif name in ("open", "openat", "close"):
            ret(-1 & 0xFFFFFFFFFFFFFFFF)

        elif name in ("read", "write", "pread64", "pwrite64"):
            ret(-1 & 0xFFFFFFFFFFFFFFFF)

        elif name in ("stat", "fstat", "lstat", "access"):
            ret(-1 & 0xFFFFFFFFFFFFFFFF)

        elif name in ("mkdir", "rmdir", "unlink", "unlinkat", "rename",
                      "fsync", "ftruncate64", "fcntl", "poll",
                      "mmap", "munmap"):
            ret(0)

        elif name == "lseek64":
            ret(-1 & 0xFFFFFFFFFFFFFFFF)

        elif name in ("opendir", "closedir", "readdir", "dirfd", "fdopendir"):
            ret(0)

        elif name in ("readlink", "realpath"):
            ret(0)

        elif name in ("dl_iterate_phdr",):
            ret(0)

        elif name == "dlsym":
            ret(0)

        elif name == "dl_iterate_phdr":
            ret(0)

        # --- stdio FILE* globals (__sF = bionic stdin/stdout/stderr array) ---
        elif name in ("stdout", "stderr", "stdin"):
            ret(UTIL_BASE + 16)

        # --- math (forward to host) ---
        elif name in ("cos", "cosf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.cos(v)))[0])
        elif name in ("sin", "sinf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.sin(v)))[0])
        elif name in ("tan",):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.tan(v)))[0])
        elif name in ("exp", "expf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.exp(v)))[0])
        elif name in ("log", "logf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            r = math.log(abs(v)) if v else 0.0
            ret(struct.unpack("<Q", struct.pack("<d", r))[0])
        elif name in ("log2",):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            r = math.log2(abs(v)) if v else 0.0
            ret(struct.unpack("<Q", struct.pack("<d", r))[0])
        elif name in ("log10",):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            r = math.log10(abs(v)) if v else 0.0
            ret(struct.unpack("<Q", struct.pack("<d", r))[0])
        elif name in ("pow", "powf"):
            a = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            b2 = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X1)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.pow(a, b2)))[0])
        elif name in ("sqrt", "sqrtf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.sqrt(abs(v))))[0])
        elif name in ("fabs", "fabsf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", abs(v)))[0])
        elif name in ("floor", "floorf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.floor(v)))[0])
        elif name in ("ceil", "ceilf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.ceil(v)))[0])
        elif name in ("round", "roundf", "rint"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", round(v)))[0])
        elif name in ("fmod", "fmodf"):
            a = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            b2 = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X1)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.fmod(a, b2) if b2 else 0.0))[0])
        elif name in ("modf", "modff"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            i_ptr = x(UC_ARM64_REG_X1)
            frac, intpart = math.modf(v)
            if i_ptr:
                wrt(i_ptr, struct.pack("<d", intpart))
            ret(struct.unpack("<Q", struct.pack("<d", frac))[0])
        elif name in ("frexp", "frexpf"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            exp_ptr = x(UC_ARM64_REG_X1)
            m, e = math.frexp(v)
            if exp_ptr:
                wrt(exp_ptr, struct.pack("<i", e))
            ret(struct.unpack("<Q", struct.pack("<d", m))[0])
        elif name in ("scalbn", "scalbnf", "ldexp"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            e = x(UC_ARM64_REG_X1)
            ret(struct.unpack("<Q", struct.pack("<d", math.ldexp(v, e)))[0])
        elif name in ("hypot",):
            a = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            b2 = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X1)))[0]
            ret(struct.unpack("<Q", struct.pack("<d", math.hypot(a, b2)))[0])
        elif name in ("acos", "acosf", "acosh"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            try:
                r = math.acos(v) if "acos" == name else math.acosh(v)
            except ValueError:
                r = 0.0
            ret(struct.unpack("<Q", struct.pack("<d", r))[0])
        elif name in ("asin", "asinf", "asinh"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            try:
                r = math.asin(v) if name == "asin" else math.asinh(v)
            except ValueError:
                r = 0.0
            ret(struct.unpack("<Q", struct.pack("<d", r))[0])
        elif name in ("atan", "atanf", "atanh", "atan2"):
            a = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            if name == "atan2":
                b2 = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X1)))[0]
                r = math.atan2(a, b2)
            elif name == "atanh":
                r = math.atanh(max(-0.9999, min(0.9999, a)))
            else:
                r = math.atan(a)
            ret(struct.unpack("<Q", struct.pack("<d", r))[0])
        elif name in ("cosh", "sinh", "tanh", "expm1", "log1p"):
            v = struct.unpack("<d", struct.pack("<Q", x(UC_ARM64_REG_X0)))[0]
            fn = {"cosh": math.cosh, "sinh": math.sinh, "tanh": math.tanh,
                  "expm1": math.expm1, "log1p": math.log1p}[name]
            ret(struct.unpack("<Q", struct.pack("<d", fn(v)))[0])
        elif name == "fesetround":
            ret(0)

        elif name in ("sysconf",):
            ret(4096)  # return page size for all sysconf queries

        else:
            _LOGGER.debug("grillcore_emu: unhandled import '%s' — returning 0", name)
            ret(0)

    # ------------------------------------------------------------------
    # High-level JNI function call
    # ------------------------------------------------------------------

    def _jni_call(self, fn_name: str, payload: bytes, uuid: str,
                  extra_key: Optional[bytes] = None) -> Optional[bytes]:
        """Call a BTManager JNI function; return result bytes or None."""
        if not self._uc:
            return None
        heap = self._heap
        assert heap is not None

        # Build full JNI symbol name
        full_name = (
            f"Java_com_sharkninja_grillcore_BTManager_00024Companion_{fn_name}"
        )
        addr = self._sym_addr.get(full_name)
        if not addr:
            _LOGGER.warning("grillcore_emu: symbol not found: %s", full_name)
            return None

        env   = self._jni_env
        this  = 0  # jobject this — NULL, not used by these functions

        data_handle = heap.new_byte_array(payload)
        uuid_handle = heap.new_string_utf(uuid)

        args: list[int]
        if extra_key is not None:
            key_handle = heap.new_byte_array(extra_key)
            args = [env, this, uuid_handle, data_handle, key_handle]
        else:
            args = [env, this, uuid_handle, data_handle]

        result_handle = self._call(addr, args)

        _LOGGER.debug("grillcore_emu: %s result_handle=%#x", fn_name, result_handle)

        # Check for error sentinels: null (0), i64::MIN (0x8000...), or -1 (0xfff...)
        if result_handle in (0, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF):
            _LOGGER.debug(
                "grillcore_emu: %s returned error (handle=%#x)", fn_name, result_handle
            )
            return None

        try:
            return heap.read_byte_array(result_handle)
        except Exception as exc:
            _LOGGER.debug("grillcore_emu: failed to read result array: %s", exc)
            return None

    def _jni_call_process_bt(self, payload: bytes, uuid: str,
                             msg_type: int) -> Optional[bytes]:
        """Call extProcessBTData with its real signature (data, uuid, type:int)."""
        if not self._uc:
            return None
        heap = self._heap
        assert heap is not None

        full_name = (
            "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData"
        )
        addr = self._sym_addr.get(full_name)
        if not addr:
            _LOGGER.warning("grillcore_emu: symbol not found: %s", full_name)
            return None

        env = self._jni_env
        this = 0
        data_handle = heap.new_byte_array(payload)
        uuid_handle = heap.new_string_utf(uuid)
        # JNI order: env, this, data(ByteArray), uuid(String), type(Int)
        args = [env, this, data_handle, uuid_handle, msg_type & 0xFFFFFFFF]

        result_handle = self._call(addr, args)
        if result_handle in (0, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF):
            return None
        try:
            return heap.read_byte_array(result_handle)
        except Exception as exc:
            _LOGGER.debug("grillcore_emu: process_bt result read failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_DEFAULT_LIB_PATH = (
    Path(__file__).parent / "lib" / "libgrillcore_android.so"
)

_emulator: Optional[GrillCoreEmulator] = None


def _default_lib_path() -> Path:
    return _DEFAULT_LIB_PATH


def get_emulator(lib_path: "Path | str | None" = None) -> GrillCoreEmulator:
    """Return (and lazily load) the singleton emulator."""
    global _emulator
    if _emulator is None:
        _emulator = GrillCoreEmulator(lib_path or _DEFAULT_LIB_PATH)
        _emulator.load()
    return _emulator
