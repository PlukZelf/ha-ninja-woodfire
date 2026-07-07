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
- **Advertisement-kanaal: OPGELOST.** Statische AES-256-CBC met vaste key/IV,
  volledig gereverse-engineerd en byte-voor-byte geverifieerd tegen de `.so`.
  Pure-Python port draait in de integratie (`custom_components/ninja_woodfire/crypto.py`)
  — geen `.so` of emulator nodig bij eindgebruikers.
- **GATT-kanaal: nog onopgelost, RE actief in uitvoering (sinds 2026-07-03).**
  Per-sessie key via challenge-response, alleen in-memory, niet direct
  offline af te leiden. Nodig om commando's te STUREN; niet nodig voor
  read-only monitoring. Drie fases (zie `docs/crypto-status.md`, sectie
  "GATT session-key attack progress"):
  - Fase 1 (wire protocol): **klaar** — handshake-framing bevestigd via
    live btsnoop-capture (CCCD-write → 20-byte challenge → 48-byte writes).
  - Fase 3 (offline emulator-replay): **UITGESLOTEN (doodlopend)** — het
    GATT-crypto-pad draait op een Rust async-runtime (tokio); tracen van
    `extProcessBTData` raakt een panic `"tried to use async function in non
    async context"`, en `decrypt_data_with_key` geeft voor elke sleutel
    dezelfde garbage (bereikt de cipher nooit). De Unicorn-emulator kan wel
    synchrone leaf-functies aanroepen (waarom de advert-crypto werkt) maar
    niet de async executor/reactor draaien die de command-crypto nodig heeft.
    De sessie-sleutel is dus NIET offline af te leiden.
  - Fase 2 (live Frida-trace): grotendeels achterhaald — zie hieronder,
    de app stuurt commando's helemaal NIET via BLE.
- Native library `libgrillcore_android.so` (Rust ARM64) is alleen nog een
  RE-oracle in lokale (niet-gecommitte) tooling, nooit gedistribueerd.

## ⛔ KERNBEPERKING — commando's sturen (2026-07-03)
- **De grill komt NOOIT op internet — dat is het hele idee.** Dit is een
  harde ontwerp-eis van de gebruiker, niet onderhandelbaar.
- Live getraced: de officiële app stuurt commando's **via de Ayla-cloud**
  (plaintext property-write `SET_Cook_Command`), NIET via BLE. Bewezen
  end-to-end met lokale (niet-gecommitte) tooling (`201 Created`).
- **MAAR:** cloud-commando's bereiken de grill alleen als de grill zélf de
  cloud pollt over WiFi. Een offline grill pollt nooit → commando blijft
  eeuwig in de cloud staan. HA-internet helpt niet; de kapotte schakel is
  cloud→grill, die het internet van de *grill* vereist.
- **Gevolg:** het enige kanaal dat een offline grill bereikt is lokaal BLE
  = het GATT-write-pad, waarvan de per-sessie-encryptie niet offline af te
  leiden is (async-runtime, zie `docs/crypto-status.md`). Lokaal commando's
  sturen is dus geblokkeerd op precies het moeilijke stuk.
- Stand van zaken: **read-only monitoring = opgelost/lokaal/shipped.**
  Commando's sturen = geen werkende route voor een air-gapped grill.
  Cloud-control blijft als optionele feature voor gebruikers die hun grill
  wél op WiFi zetten.

## Huidige prioriteit
De integratie is herschreven naar **passief BLE advertisement scannen**
(geen GATT-verbinding, read-only sensors/binary_sensors). De crypto is
opgelost en meegeleverd als pure Python. Openstaand:
1. ~~De extractie van de twee manufacturer-data AD-structs...~~ **OPGELOST,
   bevestigd live op 2026-07-03:** `service_info.raw` bevat beide AD-structs
   (company id 0x0C4F, 20 en 23 bytes) zodra de adapter actief scant; de
   `manufacturer_data`-dict houdt door een company-ID-collision maar EEN van
   de twee payloads over, dus het `raw`-pad is verplicht (niet
   optioneel/fallback-only).
   - **Actief scannen is vereist**: de 23-byte helft reist mee in de BLE
     scan response, die alleen naar actieve scanners wordt verstuurd. Bij
     passief scannen komen alleen 20-byte helften binnen en kan de state
     nooit gedecodeerd worden. De coordinator detecteert dit (30
     opeenvolgende ongepaarde 20-byte helften) en maakt een Repair issue
     aan (`passive_scanning_<address>`) die de gebruiker naar
     Instellingen → Reparaties verwijst.
2. Advertisement-veldsemantiek verder bevestigen tegen live cook-sessies
   (zie `docs/crypto-status.md`).

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

## Architectuur (herschreven, commit eb7fff5)
- **Passief advertisement scannen** — géén GATT-connect. Pipeline:
  `bluetooth.py` (passieve callback) → `crypto.py` (decrypt) →
  `advert_decode.py` (bit-fields) → `advert.py` (state-mapping) →
  `coordinator.py` (presence via advert-recency) → read-only entities.
- Alleen sensors + binary_sensors. GEEN control-entities.
- VERWIJDERD bij de rewrite: `switch.py`, `button.py`, `number.py`,
  `select.py`, `time.py`, `commands.py`, `grillcore_native.py` en de map
  `lib/` — die hadden alleen zin voor GATT-control, wat niet kan zonder de
  onopgeloste GATT-write-crypto. Niet opnieuw aanmaken.

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