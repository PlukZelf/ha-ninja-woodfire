# Contributing

Contributions are welcome once the project has a working baseline.

## Commit Style

Use small, focused commits with clear messages:

```text
docs: add protocol notes
feat(bluetooth): add discovery scanner
test(protocol): cover status payload parsing
fix(config-flow): handle missing bluetooth adapter
```

## Development Workflow

1. Keep captures and protocol notes separate from integration code.
2. Document every confirmed payload in `spec/`.
3. Add tests for protocol parsing before exposing new Home Assistant entities.
4. Avoid committing personal identifiers such as device addresses, account data, or exact home network details.

## Code Expectations

- Prefer Home Assistant's existing helper APIs and integration patterns.
- Keep Bluetooth transport concerns separate from protocol parsing.
- Keep protocol parsing deterministic and easy to test.
- Add comments only where they clarify non-obvious protocol behavior.
