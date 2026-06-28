# HA Ninja Woodfire — Claude Code Context

## Project doel
Lokale Home Assistant integratie voor de Ninja Woodfire Pro outdoor grill via BLE.
Geen cloud, geen Ninja account. GitHub: https://github.com/PlukZelf/ha-ninja-woodfire

## Omgeving
- HA Core 2026.6.4 / OS 18.0 / Supervisor 2026.06.2
- HA host: 192.168.10.100 (ARM64, aarch64-linux-musl)
- Apparaat MAC: 0C:E5:A3:19:80:52 | BLE naam: NCEU0ce5a3198052
- Android testtelefoon: Pixel 7a (42161JEHN02729), USB debugging aan
- Mac dev: macOS 11, Python 3.13, Java 10

## GATT (bevestigd)
| Characteristic | UUID | Properties |
|---|---|---|
| Service | 0000fcbb-0000-1000-8000-00805f9b34fb | - |
| Write (b002) | 0000b002-0000-1000-8000-00805f9b34fb | write |
| Notify (b003) | 0000b003-0000-1000-8000-00805f9b34fb | notify |
| Indicate (b004) | 0000b004-0000-1000-8000-00805f9b34fb | indicate |

## BLE verbindingsflow (bevestigd via HCI log)
1. CCCD write 0x0002 naar handle 0x0017 → indications aan
2. Device → 20-byte indication (challenge met session ID)
3. App → 48-byte write naar b002 (auth response, encrypted)
4. Device → 20-byte indication (auth confirm)
5. App → 48-byte write naar b002 (state request)
6. Device → 20-byte indication (device state, encrypted)

## Encryptie status
- Alles encrypted, per-sessie session key via challenge-response
- Native library: `libgrillcore_android.so` (Rust ARM64, Android Bionic — laadt NIET op HA OS)
- JNI argumentvolgorde: `extDecryptData(String uuid, byte[] data)` — uuid eerst
- Frida-route GEBLOKKEERD door native anti-Frida detectie in de .so
- Statische analyse tools gebouwd in `tools/` (zie commits van 28 juni)

## Huidige prioriteit
De `tools/infer_btcore_crypto_candidates.py` en verwante scripts draaien op de .so
om de crypto-kern functies te identificeren. Daarna Ghidra of objdump analyse van
die specifieke functies om het encryptie-algoritme te bepalen.

De .so staat op: `~/Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so`

## GrillState structuur (bevestigd via Android logcat)
```python
state: "Idle" | "Preheating" | "Cooking" | "CookComplete" | "Error" | "powered OFF"
lidOpen: bool
woodFire: bool
cookType: "NotSet" | "Timed" | "Probe"
cookMode: "NotSet" | "Grill" | "AirCrisp" | "Roast" | "Bake" | "Broil" | "Smoke" | "Dehydrate" | "MaxRoast" | "SlowCook"
oven.on / oven.desiredTemp / oven.currentTemp / oven.timeSet / oven.timeLeft
probe1/probe2: active / pluggedIn / desiredTemp / currentTemp / state / cookProgress
ignitionProgress / preheatProgress / cookProgress / restingProgress (0-100)
connectedToBluetooth / connectedToInternet / error
```

## Ontbrekende integratie-onderdelen (bouwen zodra crypto werkt)
1. `switch.py` — Connected switch (persisteren via HA storage)
2. GATT-validatie in `bluetooth.py` bij elke verbinding
3. Volledige backoff-logica in `coordinator.py`
4. Entities markeren als unavailable bij disconnect
5. `EntityCategory.DIAGNOSTIC` op error_code en connected sensors
6. Options flow in `config_flow.py`

## Commit stijl
```
feat(bluetooth): add retry logic
fix(protocol): handle empty payload
test(coordinator): cover reconnect flow
docs: update gatt spec
```

## Testcommando's
```bash
pytest tests/ -v
python tools/infer_btcore_crypto_candidates.py --so ~/Downloads/ninja_arm64/lib/arm64-v8a/libgrillcore_android.so
python tools/parse_btsnoop_att.py <btsnoop.log> --writes-only
```

## Belangrijke bevindingen
- `libgrillcore_android.so` vereist `liblog.so` (Android-specifiek) — niet beschikbaar op HA OS
- Per-sessie encryptie: twee captures van identieke grill-state verschillen 48/48 bytes
- 48-byte writes = waarschijnlijk 3× AES-16-byte blokken of 16-byte nonce + 32-byte ciphertext
- coxtor/ninja-woodfire-integration is al bekeken als referentie (cloud-aanpak, niet ons doel)
- GitHub Actions workflows aanwezig: release.yml (tag-triggered) en validate.yml

## Nooit committen
- Device MAC adressen of DSN nummers
- Ninja account credentials
- Raw BLE captures (staan in .gitignore onder captures/)
- libgrillcore_android.so (proprietary)