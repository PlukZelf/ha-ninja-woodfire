#!/usr/bin/env python3
"""Decrypt a react-native-mmkv (encrypted) store and dump its key/value pairs.

MMKV encrypted layout:
  main file : [actualSize:uint32 LE][ AES-128-CFB ciphertext ... ]  (header NOT encrypted)
  .crc file : [crcDigest:4][version:4][sequence:4][IV:16][...]      (IV = m_vector)

Usage: python decrypt_mmkv.py <store.bin> <store.crc.bin> <key_ascii>
"""
import sys, struct
from Crypto.Cipher import AES

def read_varint32(buf, pos):
    result = 0
    shift = 0
    while True:
        b = buf[pos]; pos += 1
        result |= (b & 0x7f) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos

def parse_mmkv(plain):
    """Parse decrypted MMKV body into {key: raw_value_bytes}. Last write wins."""
    kv = {}
    pos = 0
    n = len(plain)
    while pos < n:
        try:
            klen, pos = read_varint32(plain, pos)
            if klen == 0 or pos + klen > n:
                break
            key = plain[pos:pos+klen]; pos += klen
            vlen, pos = read_varint32(plain, pos)
            if pos + vlen > n:
                break
            val = plain[pos:pos+vlen]; pos += vlen
            try:
                kstr = key.decode('utf-8')
            except:
                kstr = repr(key)
            kv[kstr] = val
        except Exception:
            break
    return kv

def decode_mmkv_string(val):
    """MMKV string value = [varint32 len][utf8]. Return str or None."""
    try:
        slen, p = read_varint32(val, 0)
        if p + slen == len(val):
            return val[p:p+slen].decode('utf-8', 'replace')
    except Exception:
        pass
    return None

def main():
    store, crc, key_ascii = sys.argv[1], sys.argv[2], sys.argv[3]
    key = key_ascii.encode() if not key_ascii.startswith('hex:') else bytes.fromhex(key_ascii[4:])
    key = key.ljust(16, b'\0')[:16]

    data = open(store, 'rb').read()
    meta = open(crc, 'rb').read()

    actual_size = struct.unpack('<I', data[0:4])[0]
    iv = meta[12:28]
    cipher_data = data[4:4+actual_size]

    print(f"[*] key      : {key!r} ({key.hex()})")
    print(f"[*] actualSize: {actual_size}")
    print(f"[*] IV       : {iv.hex()}")
    print(f"[*] cipher   : {len(cipher_data)} bytes")

    cipher = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128)
    plain = cipher.decrypt(cipher_data)

    print(f"\n[*] decrypted {len(plain)} bytes. First 64: {plain[:64].hex()}")
    print(f"[*] as text  : {plain[:64].decode('latin-1')!r}\n")

    # Dump full decrypted content to a file for offline searching.
    outp = store + ".decrypted"
    open(outp, 'wb').write(plain)
    print(f"[*] full decrypted body written to {outp}\n")

    # MMKV body may have a small preamble before the first KV record — try offsets 0..8.
    best_kv, best_off = {}, 0
    for off in range(0, 9):
        kv_try = parse_mmkv(plain[off:])
        if len(kv_try) > len(best_kv):
            best_kv, best_off = kv_try, off
    print(f"[*] best KV parse at offset {best_off}: {len(best_kv)} pairs\n")
    kv = best_kv
    print(f"===== {len(kv)} key/value pairs =====")
    for k, v in kv.items():
        s = decode_mmkv_string(v)
        if s is not None and s.isprintable():
            print(f"\n  [{k}] (string, {len(v)}B):")
            print(f"    {s[:500]}")
        else:
            print(f"\n  [{k}] (raw, {len(v)}B):")
            print(f"    hex: {v[:96].hex()}")
            txt = ''.join(chr(c) if 32 <= c < 127 else '.' for c in v[:120])
            print(f"    txt: {txt}")

if __name__ == '__main__':
    main()
