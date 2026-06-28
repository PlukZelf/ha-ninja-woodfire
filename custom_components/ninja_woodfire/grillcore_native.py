"""
Native library wrapper for libgrillcore_android.so.

This module provides a Python interface to the Ninja Woodfire native
Rust library using ctypes. The library is an ARM64 ELF that can run
on Raspberry Pi 4, HA Yellow, HA Green, and other ARM64 Linux hosts.

The JNI functions in the library expect a JNI environment pointer.
We provide a minimal fake JNI env that implements only the methods
the library actually calls: NewByteArray, SetByteArrayRegion,
GetByteArrayElements, ReleaseByteArrayElements, GetArrayLength,
NewStringUTF, GetStringUTFChars, ReleaseStringUTFChars,
FindClass, GetMethodID, CallObjectMethod, DeleteLocalRef,
ExceptionCheck, ExceptionClear.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
from pathlib import Path
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# Path where the .so is expected on the HA host
_DEFAULT_LIB_PATH = Path(__file__).parent / "lib" / "libgrillcore_android.so"

# ---------------------------------------------------------------------------
# Minimal JNI environment simulation
# ---------------------------------------------------------------------------

# JNI types
jint = ctypes.c_int32
jsize = ctypes.c_int32
jbyte = ctypes.c_int8
jboolean = ctypes.c_uint8
jobject = ctypes.c_void_p
jbyteArray = ctypes.c_void_p
jstring = ctypes.c_void_p
jclass = ctypes.c_void_p
jmethodID = ctypes.c_void_p

# Our fake heap for byte arrays and strings
_HEAP: dict[int, bytes] = {}
_NEXT_ID = 0x1000


def _alloc(data: bytes) -> int:
    global _NEXT_ID
    _NEXT_ID += 8
    _HEAP[_NEXT_ID] = data
    return _NEXT_ID


def _free(ptr: int) -> None:
    _HEAP.pop(ptr, None)


# JNINativeInterface function table (768 function pointers in JNI 1.6)
# We only implement the ones the library actually needs.

_FUNC_TABLE_SIZE = 232  # number of function pointers in JNINativeInterface

# We build a ctypes Structure with a void* array large enough.
class _JNINativeInterface(ctypes.Structure):
    _fields_ = [("functions", ctypes.c_void_p * _FUNC_TABLE_SIZE)]


class _JNIEnv(ctypes.Structure):
    _fields_ = [("functions", ctypes.POINTER(_JNINativeInterface))]


# Function type aliases
_CFUNC = ctypes.CFUNCTYPE

_FN_NewByteArray = _CFUNC(jbyteArray, ctypes.c_void_p, jsize)
_FN_SetByteArrayRegion = _CFUNC(None, ctypes.c_void_p, jbyteArray, jsize, jsize, ctypes.POINTER(jbyte))
_FN_GetByteArrayElements = _CFUNC(ctypes.POINTER(jbyte), ctypes.c_void_p, jbyteArray, ctypes.POINTER(jboolean))
_FN_ReleaseByteArrayElements = _CFUNC(None, ctypes.c_void_p, jbyteArray, ctypes.POINTER(jbyte), jint)
_FN_GetArrayLength = _CFUNC(jsize, ctypes.c_void_p, jbyteArray)
_FN_NewStringUTF = _CFUNC(jstring, ctypes.c_void_p, ctypes.c_char_p)
_FN_GetStringUTFChars = _CFUNC(ctypes.c_char_p, ctypes.c_void_p, jstring, ctypes.POINTER(jboolean))
_FN_ReleaseStringUTFChars = _CFUNC(None, ctypes.c_void_p, jstring, ctypes.c_char_p)
_FN_FindClass = _CFUNC(jclass, ctypes.c_void_p, ctypes.c_char_p)
_FN_GetMethodID = _CFUNC(jmethodID, ctypes.c_void_p, jclass, ctypes.c_char_p, ctypes.c_char_p)
_FN_CallObjectMethod = _CFUNC(jobject, ctypes.c_void_p, jobject, jmethodID)
_FN_DeleteLocalRef = _CFUNC(None, ctypes.c_void_p, jobject)
_FN_ExceptionCheck = _CFUNC(jboolean, ctypes.c_void_p)
_FN_ExceptionClear = _CFUNC(None, ctypes.c_void_p)
_FN_Noop = _CFUNC(None, ctypes.c_void_p)


def _make_jni_env() -> tuple[ctypes.POINTER(_JNIEnv), list]:
    """Build a fake JNIEnv with enough function pointers to satisfy the library."""
    # Keep references so GC doesn't collect them
    refs: list = []

    def new_byte_array(env, size):
        ptr = _alloc(bytes(size))
        return ptr

    def set_byte_array_region(env, arr, start, length, buf):
        if arr not in _HEAP:
            return
        existing = bytearray(_HEAP[arr])
        raw = bytes(buf[:length])
        existing[start:start + length] = raw
        _HEAP[arr] = bytes(existing)

    def get_byte_array_elements(env, arr, is_copy):
        if arr not in _HEAP:
            return None
        data = _HEAP[arr]
        buf = (jbyte * len(data))(*[struct.unpack('b', bytes([b]))[0] for b in data])
        refs.append(buf)
        return buf

    def release_byte_array_elements(env, arr, elems, mode):
        pass

    def get_array_length(env, arr):
        if arr not in _HEAP:
            return 0
        return len(_HEAP[arr])

    def new_string_utf(env, chars):
        s = chars if isinstance(chars, bytes) else chars.encode()
        ptr = _alloc(s + b'\x00')
        return ptr

    def get_string_utf_chars(env, s, is_copy):
        if s not in _HEAP:
            return b""
        return _HEAP[s].rstrip(b'\x00')

    def release_string_utf_chars(env, s, chars):
        pass

    def find_class(env, name):
        return _alloc(name if isinstance(name, bytes) else name.encode())

    def get_method_id(env, cls, name, sig):
        return _alloc(b"method")

    def call_object_method(env, obj, method):
        return None

    def delete_local_ref(env, obj):
        _free(obj)

    def exception_check(env):
        return 0

    def exception_clear(env):
        pass

    def noop(env):
        pass

    # JNI function table indices (JNI 1.6 spec order)
    # Index 0-3: reserved
    # Index 4: GetVersion
    # ...
    # We map by known indices:
    IDX = {
        'GetVersion': 4,
        'FindClass': 6,
        'GetMethodID': 33,
        'CallObjectMethod': 36,
        'NewStringUTF': 167,
        'GetStringUTFChars': 169,
        'ReleaseStringUTFChars': 170,
        'GetArrayLength': 171,
        'NewByteArray': 186,
        'GetByteArrayElements': 188,
        'ReleaseByteArrayElements': 192,
        'SetByteArrayRegion': 208,
        'DeleteLocalRef': 23,
        'ExceptionCheck': 228,
        'ExceptionClear': 17,
    }

    table = _JNINativeInterface()

    cb_new_byte_array = _FN_NewByteArray(new_byte_array)
    cb_set_byte_array = _FN_SetByteArrayRegion(set_byte_array_region)
    cb_get_byte_array = _FN_GetByteArrayElements(get_byte_array_elements)
    cb_rel_byte_array = _FN_ReleaseByteArrayElements(release_byte_array_elements)
    cb_get_arr_len = _FN_GetArrayLength(get_array_length)
    cb_new_str = _FN_NewStringUTF(new_string_utf)
    cb_get_str = _FN_GetStringUTFChars(get_string_utf_chars)
    cb_rel_str = _FN_ReleaseStringUTFChars(release_string_utf_chars)
    cb_find_class = _FN_FindClass(find_class)
    cb_get_method = _FN_GetMethodID(get_method_id)
    cb_call_obj = _FN_CallObjectMethod(call_object_method)
    cb_del_ref = _FN_DeleteLocalRef(delete_local_ref)
    cb_exc_check = _FN_ExceptionCheck(exception_check)
    cb_exc_clear = _FN_ExceptionClear(exception_clear)
    noop_cb = _FN_Noop(noop)

    cbs = [cb_new_byte_array, cb_set_byte_array, cb_get_byte_array,
           cb_rel_byte_array, cb_get_arr_len, cb_new_str, cb_get_str,
           cb_rel_str, cb_find_class, cb_get_method, cb_call_obj,
           cb_del_ref, cb_exc_check, cb_exc_clear, noop_cb]
    refs.extend(cbs)

    for name, idx in IDX.items():
        cb = {
            'NewByteArray': cb_new_byte_array,
            'SetByteArrayRegion': cb_set_byte_array,
            'GetByteArrayElements': cb_get_byte_array,
            'ReleaseByteArrayElements': cb_rel_byte_array,
            'GetArrayLength': cb_get_arr_len,
            'NewStringUTF': cb_new_str,
            'GetStringUTFChars': cb_get_str,
            'ReleaseStringUTFChars': cb_rel_str,
            'FindClass': cb_find_class,
            'GetMethodID': cb_get_method,
            'CallObjectMethod': cb_call_obj,
            'DeleteLocalRef': cb_del_ref,
            'ExceptionCheck': cb_exc_check,
            'ExceptionClear': cb_exc_clear,
        }.get(name, noop_cb)
        table.functions[idx] = ctypes.cast(cb, ctypes.c_void_p).value

    env_inner = _JNIEnv()
    env_inner.functions = ctypes.pointer(table)
    refs.append(table)
    refs.append(env_inner)

    env_ptr = ctypes.pointer(env_inner)
    refs.append(env_ptr)

    return env_ptr, refs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class GrillCoreNative:
    """Thin wrapper around libgrillcore_android.so BT functions."""

    def __init__(self, lib_path: Path | str = _DEFAULT_LIB_PATH) -> None:
        self._lib_path = Path(lib_path)
        self._lib: Optional[ctypes.CDLL] = None
        self._env_ptr = None
        self._refs: list = []

    def available(self) -> bool:
        """Return True if the native library exists and loaded successfully."""
        return self._lib is not None

    def load(self) -> bool:
        """Load the native library. Return True on success."""
        if not self._lib_path.exists():
            _LOGGER.warning(
                "libgrillcore_android.so not found at %s. "
                "Copy the library from the Ninja app APK to enable local BLE.",
                self._lib_path,
            )
            return False
        try:
            lib = ctypes.CDLL(str(self._lib_path))
            self._lib = lib
            self._env_ptr, self._refs = _make_jni_env()
            _LOGGER.debug("Loaded libgrillcore_android.so from %s", self._lib_path)
            return True
        except OSError as err:
            _LOGGER.error("Failed to load libgrillcore_android.so: %s", err)
            return False

    def _raw_env(self) -> ctypes.c_void_p:
        return ctypes.cast(self._env_ptr, ctypes.c_void_p)

    def decrypt_data(self, payload: bytes, uuid: str) -> Optional[bytes]:
        """
        Decrypt a BLE indication payload using the device UUID as key context.

        Calls: extDecryptData(JNIEnv*, jobject, jbyteArray data, jstring uuid)
        Returns decrypted bytes or None on failure.
        """
        if not self._lib:
            return None
        try:
            fn = self._lib.Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData
            fn.restype = jbyteArray
            fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, jbyteArray, jstring]

            # Build jbyteArray for payload
            data_ptr = _alloc(payload)
            uuid_ptr = _alloc(uuid.encode() + b'\x00')

            env = self._raw_env()
            result_ptr = fn(env, None, data_ptr, uuid_ptr)

            if not result_ptr or result_ptr not in _HEAP:
                return None

            result = _HEAP[result_ptr]
            _free(data_ptr)
            _free(uuid_ptr)
            return result
        except Exception as err:
            _LOGGER.debug("decrypt_data error: %s", err)
            return None

    def encrypt_data(self, payload: bytes, uuid: str) -> Optional[bytes]:
        """
        Encrypt a BLE command payload.

        Calls: extEncryptData(JNIEnv*, jobject, jbyteArray data, jstring uuid)
        """
        if not self._lib:
            return None
        try:
            fn = self._lib.Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData
            fn.restype = jbyteArray
            fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, jbyteArray, jstring]

            data_ptr = _alloc(payload)
            uuid_ptr = _alloc(uuid.encode() + b'\x00')

            env = self._raw_env()
            result_ptr = fn(env, None, data_ptr, uuid_ptr)

            if not result_ptr or result_ptr not in _HEAP:
                return None

            result = _HEAP[result_ptr]
            _free(data_ptr)
            _free(uuid_ptr)
            return result
        except Exception as err:
            _LOGGER.debug("encrypt_data error: %s", err)
            return None

    def process_bt_data(self, payload: bytes, uuid: str) -> Optional[bytes]:
        """
        Process raw BLE data through the native state machine.

        Calls: extProcessBTData(JNIEnv*, jobject, jbyteArray data, jstring uuid)
        Returns parsed state bytes or None.
        """
        if not self._lib:
            return None
        try:
            fn = self._lib.Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData
            fn.restype = jbyteArray
            fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, jbyteArray, jstring]

            data_ptr = _alloc(payload)
            uuid_ptr = _alloc(uuid.encode() + b'\x00')

            env = self._raw_env()
            result_ptr = fn(env, None, data_ptr, uuid_ptr)

            if not result_ptr or result_ptr not in _HEAP:
                return None

            result = _HEAP[result_ptr]
            _free(data_ptr)
            _free(uuid_ptr)
            return result
        except Exception as err:
            _LOGGER.debug("process_bt_data error: %s", err)
            return None


# Singleton instance
_native: Optional[GrillCoreNative] = None


def get_native(lib_path: Path | str = _DEFAULT_LIB_PATH) -> GrillCoreNative:
    """Return the singleton GrillCoreNative instance, loading if needed."""
    global _native
    if _native is None:
        _native = GrillCoreNative(lib_path)
        _native.load()
    return _native
