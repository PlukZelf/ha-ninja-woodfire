# Architecture

## Overview

The integration is intended to run fully locally inside Home Assistant. It will communicate with the Ninja Woodfire Pro device over Bluetooth Low Energy and translate device state into Home Assistant entities.

The project is split into three layers:

1. Bluetooth client: connects to the device, subscribes to notifications, and writes commands.
2. Protocol layer: parses notification payloads and builds command payloads.
3. Home Assistant integration: exposes devices, entities, config flow, diagnostics, and repairs.

## Bluetooth Strategy

The previous investigation showed that obtaining Android HCI logs can be unreliable on recent Pixel devices. The preferred path is direct discovery from the Raspberry Pi or the Home Assistant host using Python and `bleak`.

Initial tooling should:

- scan for nearby BLE devices;
- connect to the Ninja device;
- list services and characteristics;
- subscribe to candidate notification characteristics;
- log raw payloads with timestamps;
- avoid writing commands until their meaning is understood.

## Expected Home Assistant Structure

```text
custom_components/ninja_woodfire/
  __init__.py
  manifest.json
  config_flow.py
  const.py
  coordinator.py
  bluetooth.py
  protocol.py
  sensor.py
  switch.py
  number.py
  select.py
  diagnostics.py
```

The exact entity set should follow the discovered protocol rather than assumptions from the mobile app.

## Data Flow

```text
Ninja Woodfire Pro
  -> BLE notifications
  -> Bluetooth client
  -> Protocol parser
  -> Data coordinator
  -> Home Assistant entities
```

Control commands should flow in the opposite direction only after the protocol has been documented and validated.

## Safety Notes

Cooking appliances should be treated conservatively. The integration should not send unknown payloads, bypass safety states, or expose controls before the valid ranges and device behavior are understood.

The first working version should prefer read-only monitoring. Control can be added later with explicit validation and clear error handling.
