# PAIRING DEBUG logging breakthrough (2026-07-06, avond)

## Wat gevonden is
De gepatchte app-build heeft **`PAIRING DEBUG` crypto-logging** ingeschakeld.
Tijdens een verse BLE-connect + commando logt de app naar logcat (plaintext):

```
grillcore::bt::library: PAIRING DEBUG: encrypt data UUID: "<MAC>"
bluetoothcore::btcore:   PAIRING DEBUG encrypt data sessionID: 2945844535
ReactNativeBleManager:   Write to: <MAC>
ReactNativeBleManager:   Message(32): 44B006E0...9E0AE995   <- 32B ciphertext to b002
BluetoothGatt:           writeCharacteristic() uuid 0000b002...
```

En symmetrisch voor **decrypt data** (inkomende state).

## Wat dit oplevert (hard, plaintext uit de log)
- **sessionID = 2945844535** (= 0xAF900B37, 32-bit) — de per-sessie identifier.
- **wire-ciphertext**: `ReactNativeBleManager: Message(N): <hex>` logt ELK
  b002-bericht in plaintext hex. Gezien: een 32B (auth) en een 64B (state).
- **522 encrypt/decrypt-events** in één pairing-venster (de app is chatty).

## Wat nog ONTBREEKT (net buiten de log)
De `PAIRING DEBUG`-regel logt UUID + sessionID, maar NIET de key of de
plaintext-buffer. De ciphertext staat in de aparte `Message()`-regel. Dus we
hebben (sessionID, ciphertext) maar nog niet (key, plaintext) voor hetzelfde
event.

## De volgende, kansrijke stap
De functie in `grillcore::bt::library` die "PAIRING DEBUG: encrypt data" print
heeft op dat punt key + plaintext + ciphertext in scope. Hook die functie
(anker: de log-string, of het adres eromheen) en dump de buffers. Dit is
GEEN async-abort-risico want de encrypt draait synchroon in deze pairing-flow
(de log verschijnt normaal). Dan:
- (key, ciphertext, plaintext) -> tools/crypto_puzzle/cipher_solver.py vindt de mode
- (device_key/root, sessionID/challenge, key) -> derive_solver.py vindt de KDF
- de sessionID (2945844535) is waarschijnlijk de challenge-input of eruit afgeleid.

## Ook ontdekt deze sessie
- AWS device-gateway (SigV4-signed): a `<host>/householdsEndUser/...` endpoint
  (host in .env) — vereist AWS SigV4 request signing (zag "AWS SIGNATURE
  VALIDATION FAILED"), niet enkel een api-key. household_id + okta_user_id in .env.
- s3-sts gateway + api_key (EU) staan in .env. Device key komt hier versleuteld
  door en wordt native ontsleuteld — niet als platte waarde in cloud/JS/log.
- Ayla `lanip_key` (32ch base64) opgehaald (offline grill), in _re_work/.
- `device_key: 3855390` in Ayla properties = integer device-ID (valse vriend),
  NIET de crypto-sleutel.

## Data (gitignored)
- tools/_re_work/wire_capture.json — sessionID + de 2 wire-messages.
- tools/_re_work/logcat_repair.txt — volledige pairing-logcat (bevat DSN/MAC/tokens).
