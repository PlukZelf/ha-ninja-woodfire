# Roadmap

## Sprint 0: Repository Foundation

- [x] Create the repository structure.
- [x] Add project documentation placeholders and first content.
- [x] Add an initial GitHub remote.
- [x] Make the first commit.

## Sprint 1: Bluetooth Discovery

- [x] Add a `bleak`-based discovery tool.
- [x] Scan for the Ninja Woodfire Pro device.
- [x] Record GATT services and characteristics.
- [ ] Document notification characteristics and observed payloads.

## Sprint 2: Protocol Research

There are TWO separate BLE channels with unrelated crypto (see
[docs/crypto-status.md](docs/crypto-status.md) for full technical detail):
the passive **advertisement** channel (static key, fully decoded, no
connection needed) and the **GATT** channel used after `Connect` (per-session
key, unsolved, needed only for sending commands).

- [x] Reverse-engineer the advertisement crypto (static AES-256 + whitening,
      verified via a Unicorn-emulator oracle against the real `.so`).
- [x] Decode the advertisement's full bit-packed field layout (344 bits, 43
      bytes — header + MAC + probe1/probe2 blocks + final field).
- [x] Map field semantics against real cook sessions: cook mode, remaining/
      total cook time, oven temperature, target temperature, probe1
      temperature, probe plugged-in/target-set flags, probe target
      temperature.
- [ ] Port the advertisement crypto to pure Python (currently depends on an
      emulator + the proprietary `.so`, dev-only — see "Pure-Python port
      attempt" in docs/crypto-status.md for exactly what's blocking this).
- [ ] Finish mapping the remaining fields (preheat progress, the `extra_byte`
      after the MAC, the rolling final field, probe2 once tested with a
      second physical probe).
- [ ] Capture status notifications during normal app usage or direct GATT
      sessions to start on the (separate, still fully open) GATT command
      channel.
- [ ] Identify command writes for safe read-only and control operations
      over GATT.
- [x] Create a structured protocol specification in `spec/` (GATT service
      shape) and `docs/crypto-status.md` (crypto + field findings).

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

### Planned control entities

- [ ] **Cook function** (`select`) — Grill / Smoke / AirCrisp (Air Fry) / Roast / Bake / Broil / Dehydrate / MaxRoast / SlowCook.
- [ ] **Cook type** (`select` or `switch`) — probe (thermometer) vs. time-based cooking.
- [ ] **Target temperature** (`number`) — with per-mode min/max limits.
- [ ] **Cook time** (`number` / duration) — for time-based cooking.
- [ ] **Wood flavor** (`select`) — pellet flavor selection.

> All control entities depend on write support to the grill; they land after
> the protocol work in Sprint 2 is complete.
