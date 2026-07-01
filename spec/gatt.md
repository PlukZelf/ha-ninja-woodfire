# GATT Specification

This document records confirmed Bluetooth Low Energy GATT details for the Ninja Woodfire Pro integration.

> **Note:** this covers the GATT (post-`Connect`) channel only, used for
> sending commands. Its session-key crypto remains unsolved. For **reading**
> grill state (temperatures, cook mode, timers, probes), the **passive
> advertisement** channel is a separate, already-decoded path that needs no
> connection at all — see [docs/crypto-status.md](../docs/crypto-status.md).

## Confirmed Device

Observed with nRF Connect:

- Advertised name pattern: `NCEU<lowercase-address-without-colons>`
- Local address observed during research: redacted

Do not treat the observed address as stable across all devices. It is local capture data and should not be used in integration code.

## Primary Service

| Purpose | UUID |
| --- | --- |
| Ninja service | `0000fcbb-0000-1000-8000-00805f9b34fb` |

## Characteristics

| Purpose | UUID | Properties | Status |
| --- | --- | --- | --- |
| Read | `0000b001-0000-1000-8000-00805f9b34fb` | read | Confirmed by nRF Connect |
| Write | `0000b002-0000-1000-8000-00805f9b34fb` | write | Confirmed by nRF Connect, command format unknown |
| Notify | `0000b003-0000-1000-8000-00805f9b34fb` | notify | Confirmed by nRF Connect |
| Indicate | `0000b004-0000-1000-8000-00805f9b34fb` | indicate | Confirmed by nRF Connect |

## Safety

The write characteristic is documented only as a discovered endpoint. Do not send payloads until the command format and safety behavior are understood.

The next research step is to subscribe to `b003` and `b004`, then record notifications while the appliance changes state.

## Observed Payloads

### Indicate: `b004`

Observed payloads after subscribing to the indicate characteristic:

```text
# sample 1
a5 a0 30 31 50 c1 69 27 8d c7 a8 44 4c e0 36 87
4d f5 df 2d 64 f9 3b db 30 4a 37 ed d4 b8 35 e6
eb ce 48 9b b5 c4 da 70 f6 7a f8 58 7e 21 6a 39
20 5b 82 45 4b c3 68 1b 49 28 1a b3 c7 8a c1 c4

# sample 2
64 8e de 4f bc 94 61 59 e8 43 58 6b 7b 3d 58 55
4a f3 a4 17 48 c3 91 5e 17 4b 44 be 17 01 b1 dd
04 e1 cf f2 54 53 d1 70 83 e6 18 34 44 92 28 56
9d f3 27 ae cf 8d 1a 42 9f e1 4e cf ba e0 65 64
```

Length: 64 bytes.

Current interpretation: unknown. The payloads do not appear to be plain text and may include encrypted or session-specific data. More samples are needed while changing appliance state.

## Android HCI Capture Notes

An Android HCI snoop capture from the official app showed:

- a client configuration write to enable indications;
- two 48-byte `Write Request` packets to a vendor characteristic;
- 20-byte indications returned by the device after those writes.

The Android capture used different numeric ATT handles than BlueZ on Home Assistant, but the flow matches the known vendor service shape:

- write characteristic: `b002`;
- indicate characteristic: `b004`;
- client characteristic configuration descriptor next to `b004`.

The raw write payloads are not documented here because they appear session-specific and should not be replayed blindly.
