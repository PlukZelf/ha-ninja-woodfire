# GATT Specification

This document records confirmed Bluetooth Low Energy GATT details for the Ninja Woodfire integration.

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
