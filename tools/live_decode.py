"""Live, continuous BLE advert decode -- no phone/app needed.

Scans for the grill's adverts, pairs the two same-company-ID manufacturer-
data AD structures per packet (see scan_grill_raw.py for why that needs
special handling on Windows), decodes them via the Unicorn emulator oracle
(tools/grillcore_emu.py), and prints the resulting field values so they can
be correlated against known real grill/app state changes.
"""
import asyncio
import os
import sys
import time

from bleak import BleakScanner

sys.path.insert(0, os.path.dirname(__file__))
from grillcore_emu import GrillCoreEmulator
from decode_advert_fields import decode as decode_fields

SO_PATH = os.path.join(os.path.dirname(__file__), "artifacts", "extracted", "lib", "arm64-v8a", "libgrillcore_android.so")
COMPANY_ID = 3151  # 0x0C4F

emu = GrillCoreEmulator(SO_PATH)
assert emu.load(), "emulator failed to load"

last_combined = None


def decode_and_print(half1: bytes, half2: bytes) -> None:
    global last_combined
    d1 = emu._decode_advert_half(half1)
    d2 = emu._decode_advert_half(half2)
    if d1 is None or d2 is None:
        print("  [!] decode failed for one half")
        return
    combined = d1 + d2
    if combined == last_combined:
        return  # unchanged since last print, skip noise
    last_combined = combined

    ts = time.strftime("%H:%M:%S")
    fields = decode_fields(combined)
    print(f"\n[{ts}] --- new decoded state ---")
    print("header:", fields["header"])
    print("extra_byte:", hex(fields["extra_byte"]))
    print("probe1:", fields["probes"][0])
    print("probe2:", fields["probes"][1])
    print("final:", hex(fields["final"]))


def callback(device, advertisement_data):
    sender, raw_data = advertisement_data.platform_data
    blobs = []
    for args in filter(lambda d: d is not None, raw_data):
        for m in args.advertisement.manufacturer_data:
            if m.company_id == COMPANY_ID:
                blobs.append(bytes(m.data))
    by_len = {len(b): b for b in blobs}
    if 20 in by_len and 23 in by_len:
        decode_and_print(by_len[20], by_len[23])


async def main():
    print("Scanning for grill adverts... (Ctrl+C to stop)")
    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    await scanner.stop()


if __name__ == "__main__":
    asyncio.run(main())
