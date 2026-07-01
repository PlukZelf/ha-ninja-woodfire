#!/usr/bin/env python3
"""Decrypt Ninja Woodfire BLE frames with a known AES key (from Frida dump).

The BLE crypto is AES-128-CBC with PKCS7 padding (RustCrypto aes-0.8.4 +
block-modes). Frame layout per reversing: many frames carry a 16-byte random IV
prefix followed by the ciphertext, but the exact framing is confirmed by the
Frida dump (which prints KEY/IV/CT/PT separately). Use this to replay that
offline and to batch-decrypt captured frames.

Usage:
  # direct: decrypt one ct with explicit key+iv (verify against Frida PT)
  python decrypt_with_key.py --key <hex32> --iv <hex32> --ct <hex>

  # iv-prefixed: first 16 bytes of the frame are the IV
  python decrypt_with_key.py --key <hex32> --iv-prefixed --ct <hex>
"""
from __future__ import annotations
import argparse

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    raise SystemExit("pip install cryptography")


def aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(ct) + dec.finalize()


def unpad_pkcs7(b: bytes) -> bytes:
    if not b:
        return b
    n = b[-1]
    if 1 <= n <= 16 and b[-n:] == bytes([n]) * n:
        return b[:-n]
    return b  # not padded / unknown


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="AES key, hex (16 or 32 bytes)")
    ap.add_argument("--iv", help="IV, hex 16 bytes")
    ap.add_argument("--iv-prefixed", action="store_true",
                    help="take IV from the first 16 bytes of --ct")
    ap.add_argument("--ct", required=True, help="ciphertext, hex")
    args = ap.parse_args()

    key = bytes.fromhex(args.key)
    ct = bytes.fromhex(args.ct.replace(" ", ""))

    if args.iv_prefixed:
        iv, ct = ct[:16], ct[16:]
    elif args.iv:
        iv = bytes.fromhex(args.iv)
    else:
        iv = bytes(16)

    if len(ct) % 16 != 0:
        print(f"[!] ciphertext length {len(ct)} not a multiple of 16 -- "
              f"framing may include a header/tag; trimming to nearest block")
        ct = ct[: len(ct) - (len(ct) % 16)]

    raw = aes_cbc_decrypt(key, iv, ct)
    pt = unpad_pkcs7(raw)
    print(f"key={key.hex()}  iv={iv.hex()}")
    print(f"raw plaintext ({len(raw)}B): {raw.hex(' ')}")
    print(f"unpadded     ({len(pt)}B): {pt.hex(' ')}")
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in pt)
    print(f"ascii: {printable}")


if __name__ == "__main__":
    main()
