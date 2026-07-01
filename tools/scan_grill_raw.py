"""Scan specifically for the grill's adverts (company 0x0C4F / 3151) and
recover BOTH manufacturer-data AD structures from the SAME packet.

bleak's Windows/WinRT backend merges all manufacturer-data sections of a
single advertisement into one dict keyed by company_id -- since this grill
uses the SAME company_id (0x0C4F) for both of its two AD structures (a 20-
and a 23-byte payload), bleak's dict silently keeps only the LAST one and
drops the other (see bleak/backends/winrt/scanner.py:161-162). We bypass
this by reaching into `advertisement_data.platform_data`, which exposes the
raw WinRT event args -- from there `args.advertisement.manufacturer_data`
is the original list/vector with both entries intact.
"""
import asyncio
from bleak import BleakScanner

COMPANY_ID = 3151  # 0x0C4F
count = 0


def callback(device, advertisement_data):
    global count
    sender, raw_data = advertisement_data.platform_data
    blobs = []
    for args in filter(lambda d: d is not None, raw_data):
        for m in args.advertisement.manufacturer_data:
            if m.company_id == COMPANY_ID:
                blobs.append(bytes(m.data))
    if not blobs:
        return
    count += 1
    lens = [len(b) for b in blobs]
    print(f"#{count} addr=...{device.address[-8:]} rssi={advertisement_data.rssi} "
          f"n_blobs={len(blobs)} lens={lens}")
    for b in blobs:
        print(f"    {len(b):2d}B: {b.hex()}")
    if count >= 15:
        raise KeyboardInterrupt


async def main():
    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        await asyncio.sleep(20)
    except KeyboardInterrupt:
        pass
    await scanner.stop()


asyncio.run(main())
