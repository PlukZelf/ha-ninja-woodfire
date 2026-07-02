"""Pure-Python LSB-first bit-field decoder for the 43-byte decrypted advert.

Ported verbatim from tools/decode_advert_fields.py. See docs/crypto-status.md
for the field-width derivation. Do NOT change the width tables or read order.
"""

from __future__ import annotations

HEADER_WIDTHS = [8, 8, 5, 4, 5, 7, 1, 2, 7, 1, 1, 1, 1, 0x11, 10, 10, 10, 6, 0x10, 8, 0x20]
MAC_WIDTHS = [8] * 6
EXTRA_BYTE_WIDTH = 8
PROBE_WIDTHS = [3, 1, 1, 3, 4, 4, 5, 10, 0x11]
FINAL_WIDTH = 0x20

assert len(HEADER_WIDTHS) == 21
assert sum(HEADER_WIDTHS) == 160
assert sum(PROBE_WIDTHS) == 48


def read_bits(data: bytes, bit_offset: int, num_bits: int) -> int:
    """LSB-first, byte-boundary-crossing safe bit reader."""
    result = 0
    for i in range(num_bits):
        bitpos = bit_offset + i
        byte_i = bitpos // 8
        bit_i = bitpos % 8
        if byte_i >= len(data):
            break
        bit = (data[byte_i] >> bit_i) & 1
        result |= bit << i
    return result


def decode(data: bytes) -> dict:
    """Decode a 43-byte combined (half1+half2) plaintext buffer into fields."""
    offset = 0
    out = {"header": [], "mac_bytes": [], "extra_byte": None, "probes": [], "final": None}

    for w in HEADER_WIDTHS:
        out["header"].append(read_bits(data, offset, w))
        offset += w

    for w in MAC_WIDTHS:
        out["mac_bytes"].append(read_bits(data, offset, w))
        offset += w

    out["extra_byte"] = read_bits(data, offset, EXTRA_BYTE_WIDTH)
    offset += EXTRA_BYTE_WIDTH

    for _probe_idx in range(2):
        probe = []
        for w in PROBE_WIDTHS:
            probe.append(read_bits(data, offset, w))
            offset += w
        out["probes"].append(probe)

    out["final"] = read_bits(data, offset, FINAL_WIDTH)
    offset += FINAL_WIDTH

    out["_total_bits_consumed"] = offset
    out["_total_bits_available"] = len(data) * 8
    return out
