"""Pure-Python decryption of Ninja Woodfire BLE advertisement halves.

Ported verbatim from tools/advert_crypto_port.py, which was verified
byte-for-byte against the real native libgrillcore_android.so across
7 hand-recorded vectors plus 150 random vectors. See docs/crypto-status.md.

Do NOT modify the algorithm or constants.
"""

from __future__ import annotations

from Crypto.Cipher import AES

# Static AES-256 key and IV, embedded constants recovered from the .so.
KEY_CONST = bytes.fromhex(
    "eb08bb107cb293618536fd3dee1d2f6cdbc3d888bfac8f53839704220f1f197e"
)
IV_CONST = bytes.fromhex("539ca281078468fd901e591ae1be425b")

assert len(KEY_CONST) == 32
assert len(IV_CONST) == 16


def decode_advert_half(raw: bytes) -> bytes:
    """Decode a single 17-31 byte BLE advert manufacturer-data half.

    Raises ValueError if raw is not 17..31 bytes long.
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
