# Roadmap

## Sprint 0: Repository Foundation

- [x] Create the repository structure.
- [x] Add project documentation placeholders and first content.
- [x] Add an initial GitHub remote.
- [x] Make the first commit.

## Sprint 1: Bluetooth Discovery

- [x] Add a `bleak`-based discovery tool.
- [x] Scan for the Ninja Woodfire device.
- [x] Record GATT services and characteristics.
- [ ] Document notification characteristics and observed payloads.

## Sprint 2: Protocol Research

- [ ] Capture status notifications during normal app usage or direct BLE sessions.
- [ ] Identify payloads for device state, temperature, timer, mode, and errors.
- [ ] Identify command writes for safe read-only and control operations.
- [ ] Create a structured protocol specification in `spec/`.

## Sprint 3: Home Assistant Integration

- [ ] Add the custom integration manifest.
- [ ] Implement config flow and Bluetooth discovery.
- [ ] Add coordinator and device client.
- [ ] Add first read-only entities.
- [ ] Add tests for parsing and coordinator behavior.

## Sprint 4: Control Features

- [ ] Add safe control commands once the protocol is understood.
- [ ] Add validation for cooking modes, temperature limits, and timers.
- [ ] Document known device models and firmware behavior.
- [ ] Prepare a first tagged release.
