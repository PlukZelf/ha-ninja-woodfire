"""Pure-Python port of FUN_0023085c (LSB-first bitstream reader) applied to the
AES-decoded 43-byte advert buffer, following the EXACT control flow of
FUN_0022f11c / "parse_grill_and_probe_status" (tools/artifacts/
ghidra_decompiled_advert.txt lines ~3690-3881), not a flat sequential table.

Corrects an earlier mistaken transcription (in REBOOT.md) that treated indices
21+ as flat sequential fields — the real control flow is:
  - 21 header fields (piVar30[0x0..0x14])
  - a 6-iteration loop reading piVar30[0x15..0x1a] (all width 8) -> MAC address
  - 1 more field piVar30[0x1b] (width 8)
  - a 2-iteration probe loop, each iteration reading 9 fields from a dedicated
    9-slot block: probe1 uses piVar30[0x1c..0x24], probe2 uses piVar30[0x25..0x2d]
    (the two blocks are byte-identical: [3,1,1,3,4,4,5,10,17])
  - 1 final field piVar30[0x2e] (width 32)
Total: 160 + 48 + 8 + 48 + 48 + 32 = 344 bits = 43 bytes exactly (verified).
"""

HEADER_WIDTHS = [8, 8, 5, 4, 5, 7, 1, 2, 7, 1, 1, 1, 1, 0x11, 10, 10, 10, 6, 0x10, 8, 0x20]
MAC_WIDTHS = [8] * 6
EXTRA_BYTE_WIDTH = 8
PROBE_WIDTHS = [3, 1, 1, 3, 4, 4, 5, 10, 0x11]
FINAL_WIDTH = 0x20

assert len(HEADER_WIDTHS) == 21
assert sum(HEADER_WIDTHS) == 160
assert sum(PROBE_WIDTHS) == 48


def read_bits(data: bytes, bit_offset: int, num_bits: int) -> int:
    """Exact port of FUN_0023085c: LSB-first, byte-boundary-crossing safe."""
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


if __name__ == "__main__":
    # NOTE: bytes 20-25 below (the "MAC bytes" field) are a placeholder, NOT a
    # real device MAC address (never commit real MAC addresses, see CLAUDE.md).
    # All other bytes are from a real decoded capture, kept for the sanity-check
    # markers (byte 0x13=='4', last byte=='!').
    combined = bytes.fromhex(
        "000de708200088662006040000880e2d36cd9d34"
        "aabbccddeeff0e0800000000000000000000001b1f8621"
    )
    print(f"input: {len(combined)} bytes = {len(combined)*8} bits\n")
    result = decode(combined)

    print("HEADER fields (index: value):")
    for i, v in enumerate(result["header"]):
        print(f"  [{i:2d}] width={HEADER_WIDTHS[i]:2d}  value={v}")

    mac_hex = " ".join(f"{b:02x}" for b in result["mac_bytes"])
    print(f"\nMAC bytes: {mac_hex}")
    print(f"extra byte: {result['extra_byte']:#04x}")

    for i, probe in enumerate(result["probes"]):
        print(f"\nprobe {i+1}: {probe}")
        for j, v in enumerate(probe):
            print(f"    [{j}] width={PROBE_WIDTHS[j]:2d}  value={v}")

    print(f"\nfinal field (32-bit): {result['final']:#x} ({result['final']})")
    print(f"\ntotal bits consumed: {result['_total_bits_consumed']} / available: {result['_total_bits_available']}")
