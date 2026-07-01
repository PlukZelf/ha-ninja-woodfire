"""Verify GrillCoreEmulator.decode_advert() against a real captured advert.

Requires your own extracted libgrillcore_android.so (never committed, see
CLAUDE.md) at tools/artifacts/extracted/lib/arm64-v8a/, or set NINJA_SO_PATH.

NOTE: does NOT hardcode a real device's MAC address or decoded plaintext
(never commit those, see CLAUDE.md). Instead this checks the same
sanity-check markers the real native parser (FUN_0022f11c) itself validates
before trusting a decoded buffer — this works for ANY captured advert, not
just one specific device/session. Fill in RAW_ADVERT_HEX below with your own
capture (see tools/frida_replay_advert.js for how to grab one) before running
locally; do not commit your own filled-in value either.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from grillcore_emu import GrillCoreEmulator
from decode_advert_fields import decode as decode_fields

SO_PATH = os.environ.get(
    "NINJA_SO_PATH",
    os.path.join(
        os.path.dirname(__file__),
        "artifacts", "extracted", "lib", "arm64-v8a", "libgrillcore_android.so",
    ),
)

# Fill in with your own captured raw ~62-byte advert (hex, spaces optional).
# Left blank in the committed version — this is per-device/session data.
RAW_ADVERT_HEX = os.environ.get("NINJA_RAW_ADVERT_HEX", "")

if not RAW_ADVERT_HEX:
    sys.exit(
        "Set NINJA_RAW_ADVERT_HEX to your own captured raw advert bytes "
        "(see tools/frida_replay_advert.js) before running this script."
    )

emu = GrillCoreEmulator(SO_PATH)
assert emu.load(), "emulator failed to load"

raw_advert = bytes.fromhex(RAW_ADVERT_HEX.replace(" ", ""))
print("raw advert:", len(raw_advert), "bytes")

decoded = emu.decode_advert(raw_advert)
assert decoded is not None, "decode_advert returned None"
print("decoded:", len(decoded), "bytes:", decoded.hex())

# Same two sanity markers FUN_0022f11c itself checks before trusting the buffer.
assert len(decoded) == 43, f"expected 43 decoded bytes, got {len(decoded)}"
assert decoded[0x13] in (0x34, 0x35, 0x36), f"unexpected model byte: {decoded[0x13]:#x}"
assert decoded[-1] in (0x21, 0x23), f"unexpected sanity marker: {decoded[-1]:#x}"
print("\n[OK] decode_advert() output passes the parser's own sanity checks.")

fields = decode_fields(decoded)
mac = " ".join(f"{b:02x}" for b in fields["mac_bytes"])
print(f"[OK] parsed MAC: {mac}")
print("\nAll checks passed.")
