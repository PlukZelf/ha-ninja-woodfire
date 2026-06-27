# HA Ninja Woodfire

Local Home Assistant integration for Ninja Woodfire outdoor cooking devices.

This project aims to control and monitor a Ninja Woodfire device over local Bluetooth, without relying on a cloud service. The protocol is still being researched, so the first development phase focuses on discovery, captures, documentation, and a clean Home Assistant architecture.

## Goals

- Discover the Bluetooth GATT services and characteristics exposed by the device.
- Reverse-engineer status updates and commands for core cooking workflows.
- Build a local Home Assistant custom integration.
- Keep the project suitable for open-source publication from the first commit.

## Current Status

The repository is in early setup. No usable Home Assistant integration is available yet.

Planned first milestones:

1. Document the architecture and development workflow.
2. Add Bluetooth discovery tooling based on Python and `bleak`.
3. Capture and document GATT services, characteristics, notifications, and commands.
4. Implement the first Home Assistant entities.

## Bluetooth Discovery

The first discovery tool is available at `tools/ble_scan.py`. It scans nearby BLE advertisements without connecting to devices or writing commands.

See [Bluetooth Discovery](docs/bluetooth-discovery.md) for setup and usage.

## Repository Layout

```text
.github/workflows/              GitHub Actions workflows
custom_components/ninja_woodfire/ Home Assistant custom integration
docs/                           Project and protocol documentation
spec/                           Protocol notes and structured specifications
captures/                       Local Bluetooth captures and discovery output
tests/                          Automated tests
tools/                          Development and reverse-engineering tools
```

## Development Principles

- Local-first: the integration should work without cloud dependencies.
- Small commits: each commit should have a focused purpose.
- Document discoveries as they happen.
- Avoid temporary hacks in the integration path.
- Keep captured personal data and device identifiers out of public commits.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
