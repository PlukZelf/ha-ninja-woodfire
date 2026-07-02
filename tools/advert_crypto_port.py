#!/usr/bin/env python3
"""
Pure-Python port of the Ninja Woodfire BLE advertisement decryption
(the transform implemented natively by ``FUN_00230460`` /
``FUN_002315a0`` inside ``libgrillcore_android.so``).

Fully verified byte-for-byte against the real native implementation
(run under the Unicorn AArch64 emulator in ``tools/grillcore_emu.py``)
across the 7 hand-recorded test vectors below plus 75 additional
randomly generated vectors spanning every valid input length (17-31
bytes). See ``docs/crypto-status.md`` for the reverse-engineering
writeup.

Algorithm
---------
Each raw AD-structure payload "half" (17-31 bytes: one full 16-byte
block plus a 1-15 byte tail) is decoded as:

1. ``out0 = AES-256-CBC-Decrypt(KEY_CONST, IV_CONST, raw[0:16])``
   (a single 16-byte block, so this is equivalent to
   ``AES-256-ECB-Decrypt(KEY_CONST, raw[0:16]) XOR IV_CONST``).
2. Let ``tail_len = len(raw) - 16`` (1-15). Build a second 16-byte
   block: ``window = out0[tail_len:16] + raw[16:len(raw)]`` (i.e. the
   last ``16 - tail_len`` bytes of ``out0``, followed by all of the
   raw tail bytes -- always exactly 16 bytes total).
3. ``out1 = AES-256-CBC-Decrypt(KEY_CONST, IV_CONST, window)`` (same
   fixed key/IV, a fresh single-block CBC decrypt -- NOT chained from
   step 1's IV).
4. Final output = ``out0[0:tail_len] + out1`` -- exactly
   ``tail_len + 16 == len(raw)`` bytes.

Both AES calls use the SAME fixed key and IV (there is no per-message
key derivation for the advert channel -- the key is a static constant
embedded in the ``.so``). The two-call "telescoping" structure exists
because the native code processes the underlying byte stream in
16-byte AES blocks internally but the manufacturer-data payload isn't
block aligned (20 and 23-byte halves in practice), so the tail bytes
get folded into a second block built from the unused tail of the
first block's decrypted output.
"""

from Crypto.Cipher import AES

# Static AES-256 key and IV used for BOTH internal CBC-decrypt calls.
# Recovered from FUN_002309ac's row-0 constant table (raw vaddr
# 0x230a70-ish literals `__ptr[0x*]` assigned via the pattern
# `puVar9[0..3]` / `puVar9[0..1]` in that function) and confirmed
# byte-for-byte via direct emulator calls into FUN_00231934/
# FUN_002315a0 with these exact values.
KEY_CONST = bytes.fromhex(
    "eb08bb107cb293618536fd3dee1d2f6cdbc3d888bfac8f53839704220f1f197e"
)
IV_CONST = bytes.fromhex("539ca281078468fd901e591ae1be425b")

assert len(KEY_CONST) == 32
assert len(IV_CONST) == 16


def decode_advert_half(raw: bytes) -> bytes:
    """Decode a single 17-31 byte BLE advert manufacturer-data "half".

    Args:
        raw: raw bytes for one AD-structure payload half (a full
            advertisement contains two such halves, at offsets 0xb and
            0x27 of the ~62-byte raw advert -- see
            ``docs/crypto-status.md``).

    Returns:
        Decoded plaintext, same length as ``raw``.

    Raises:
        ValueError: if ``raw`` is not 17-31 bytes long (the native
            function validates this exact range and returns an error
            sentinel outside it).
    """
    n = len(raw)
    if not (17 <= n <= 31):
        raise ValueError(f"decode_advert_half: length {n} out of range 17..31")

    tail_len = n - 16  # 1..15

    cipher0 = AES.new(KEY_CONST, AES.MODE_CBC, iv=IV_CONST)
    out0 = cipher0.decrypt(raw[:16])

    window = out0[tail_len:16] + raw[16:n]
    assert len(window) == 16

    cipher1 = AES.new(KEY_CONST, AES.MODE_CBC, iv=IV_CONST)
    out1 = cipher1.decrypt(window)

    return out0[:tail_len] + out1


if __name__ == "__main__":
    # Self-test: verified vectors, no .so / emulator required to run this.
    _VECTORS = [
        ("seq20", bytes.fromhex("000102030405060708090a0b0c0d0e0f10111213"),
         bytes.fromhex("f5e3cbd0c4d9c29617e1b0ff2c3a5d3a1d5bf7b1")),
        ("zero20", bytes.fromhex("0000000000000000000000000000000000000000"),
         bytes.fromhex("63a5e1ff5983da560a1190ac1f6a4516a64f2829")),
        ("ff20", bytes.fromhex("ffffffffffffffffffffffffffffffffffffffff"),
         bytes.fromhex("46072ac68efd9bb8be94f7b2ecfffe801d69511e")),
        ("prand20", bytes.fromhex("030a11181f262d343b424950575e656c737a8188"),
         bytes.fromhex("d80d7efcd5172e9c58115fa469bebe665a26304e")),
        ("seq23", bytes.fromhex("000102030405060708090a0b0c0d0e0f10111213141516"),
         bytes.fromhex("f5e3cbd0c2ff0f07cabf4e8b3b26fb7af697ffcec8affc")),
        ("zero23", bytes.fromhex("0000000000000000000000000000000000000000000000"),
         bytes.fromhex("63a5e1ff5ed5e0f70050a2da3eb607313d554ed73ca732")),
        ("prand23", bytes.fromhex("010e1b2835424f5c697683909daab7c4d1deebf805121f"),
         bytes.fromhex("eeab4427d7544d5b398e3f86d485e4853c4b2e0dca335e")),
    ]

    all_pass = True
    for name, raw, expected in _VECTORS:
        try:
            got = decode_advert_half(raw)
            ok = got == expected
        except Exception as exc:  # noqa: BLE001
            ok = False
            got = None
            print(f"{name}: ERROR - {exc}")
        status = "PASS" if ok else "FAIL"
        print(f"{name} ({len(raw)}B): {status}")
        if not ok:
            print(f"  expected: {expected.hex()}")
            print(f"  got:      {got.hex() if got is not None else got}")
        all_pass &= ok

    print("\nAll tests passed!" if all_pass else "\nSome tests FAILED.")
