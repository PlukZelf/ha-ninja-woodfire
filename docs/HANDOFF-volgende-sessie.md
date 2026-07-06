# OVERDRACHT — volgende sessie (bijgewerkt 2026-07-07)

Lees dit eerst. Dit vervangt alle eerdere handoffs. Doel onveranderd: **HA stuurt
lokaal (BLE, air-gapped) commando's naar de Ninja Woodfire grill**. Lezen/monitoren
is al geshipped; dit gaat over SCHRIJVEN.

## 🎉 DE GROTE DOORBRAAK (2026-07-06 avond)
**De GATT-command-crypto is GEEN mysterie meer: het is AES-256-CBC (PKCS7).**
Bewezen, live, end-to-end. Zie `docs/gatt-crypto-solved.md` + gitignored
`tools/_re_work/CRYPTO_SOLVED.md`.

Twee muren die dit weken blokkeerden zijn omzeild:
1. **Async-muur** (waar de offline-emulator op doodliep): de gepatchte app-build
   logt `PAIRING DEBUG` en draait de crypto SYNCHROON in `grillcore::bt::library`.
   Frida-hooks vuren daar gewoon.
2. **Welke cipher**: capstone-disassembly van de `.so` vond de Rust-crates
   `aes-0.7.5` + `block-modes-0.8.1` + `block-padding-0.2.1` → `Cbc<Aes256,Pkcs7>`.

**Verificatie (waterdicht):** voor het ADVERT-kanaal (key kenden we al) geldt
`AES-256-CBC-decrypt(key, iv, ciphertext) == plaintext` op 4/4 blokken; één
plaintext-blok is het grill-MAC in de klare.

## ⚠️ HET ENIGE RESTPUNT — de juiste key voor de 48B wire-command
We hebben cipher + framestructuur + de 48B wire-ciphertext, maar NOG NIET de key
die exact díé 48B-write versleutelt.

- De CBC-encrypt-functie op `module+0x1315a0` VUURT betrouwbaar, maar produceert
  alleen 64B/176B outputs met herhalende patronen (= interne bitsliced AES-state),
  NOOIT een 48B output. De key die daar langskomt (`<internal-key>…`, IV `<iv>…`,
  STATISCH per grill) is dus een INTERNE stroom, niet het temp-commando.
- Brute-force getest: geen van de 6 gevangen keys × alle IV-schema's ontsleutelt
  een 48B wire-command tot een zinnig frame. Bevestigt: 48B gebruikt een ANDERE,
  nog-niet-gevangen key/encrypt-call.
- De command-key staat NIET in de JS-bundle/APK (native gegenereerd). Enige
  statische keys in de bundle = advert-key (`eb08bb10…`) en probe-key
  (`sharkninjawp1000`) — allebei NIET het command.

### Wat de volgende sessie moet doen (afgebakend, geen mysterie)
Vind de encrypt-call die een **48-byte output** produceert (= de b002 wire-write),
en vang daarvan `(key, iv, plaintext, 48B-ciphertext)`. Drie routes, voorkeur:
1. **Traceer terug vanaf de GATT-write.** In logcat gebeurt
   `BluetoothGatt.writeCharacteristic() uuid 0000b002 length=48` net na de encrypt.
   Hook de functie die de 48B-buffer opbouwt vlak vóór die write (of de
   `ReactNativeBleManager.Write` → native pad) en dump z'n input (plaintext frame)
   + de gebruikte key. Een agent kan dit statisch traceren in de `.so`.
2. **Hook de fixslice AES-core** `0x1149d8` (batch encrypt) of `0x1144e0` (round
   core) — die de agent al identificeerde — en correleer met een 48B-write.
   Lastiger (block-niveau) maar zeker raak.
3. **Her-check de JNI-exports** `extEncryptData` (0x104384) /
   `extEncryptDataWithOptionalKey` (0x1044e8): vuurden eerder niet voor cook, maar
   dat was vóór we wisten dat pairing het sync-pad gebruikt. Opnieuw proberen
   tijdens een verse connect + temp.

Zodra de juiste tuple binnen is: CBC-decrypt de 48B → plaintext-commando-frame,
leg naast de `BTLEDataType`-opcodes (zie onder), en herimplementeer encrypt in
pure Python (AES-256-CBC) voor de bleak-client → HA. **KLAAR.**

## VITALE OFFSETS (module-base-relative; base wisselt per run, offset niet)
libgrillcore_android.so:
- `0x1315a0` — `Cbc<Aes256,Pkcs7>::encrypt` entry (VUURT). ABI:
  - x1 = &key slice → key ptr @ [x1+8], len @ [x1+16] (==0x20 → AES-256)
  - x2 = &iv  slice → iv ptr @ [x2+8], 16 bytes
  - x3 = &plaintext slice → ptr @ [x3], len @ [x3+8]
  - x0 = sret out ptr → **Vec = {len@+0, ptr@+8, cap@+16}** (belangrijk: len eerst!)
- `0x114238` — AES-256 key schedule; x1 = ruwe 32-byte key.
- `0x1149d8` — fixslice batch encrypt; `0x1144e0` — round core.
- `0x131934` — logging-helper (NIET de crypto-fn; Interceptor.attach vuurt hier niet).
- `0x132ac8` — ENC orchestrator (bevat de sessionID-log site `0x1335e0`).
- PAIRING DEBUG log-strings: `0x3f14a` "encrypt data sessionID", `0x3f169` decrypt.

## FRIDA-SETUP (werkt betrouwbaar, geen instabiliteit meer)
- Toestel: Pixel 7a, NIET geroot. frida-server kan daardoor NIET spawnen/attachen
  (NotSupportedError / PermissionDeniedError). **De gepatchte Gadget-APK is
  verplicht** en STABIEL gebleken (geen degradatie zoals oude handoffs vreesden).
- Gepatchte APK: `C:/Users/micro/ninja_patched_aligned.apk` (bevat
  libfrida-gadget.so + dezelfde grillcore .so). Installeren:
  `adb uninstall com.sharkninja.ninja.connected.kitchen` (signature mismatch) dan
  `adb install -r <apk>`.
- adb ligt op `C:/Users/micro/platform-tools-dl/platform-tools/adb.exe`
  (niet op PATH). Frida 17.15.3 (python), frida-tools 14.10.4.
- Draaien: `python tools/frida_run.py <hook.js>` — attacht op "Gadget", schrijft
  {kind:write_file} naar de repo, stopt op {kind:done}. App eerst starten met
  `adb shell monkey -p com.sharkninja.ninja.connected.kitchen -c android.intent.category.LAUNCHER 1`.
- **Frida 17-gotchas (belangrijk):**
  - `Module.findExportByName` BESTAAT NIET → `Process.findModuleByName(lib).findExportByName(naam)`.
  - Memory-read: `ptr.readByteArray(n)` (NIET `Memory.readByteArray(ptr,n)`).
  - MTE-getagde pointers (`0xb4…`): lees direct OF strip top-byte
    `p.and(ptr('0x00ffffffffffffff'))` — probeer beide.
  - NOOIT JNIEnv-calls (`GetByteArrayElements/Region`) vanuit een fn op de
    tokio-async-runtime → panic "abort was called". Lees RUW geheugen.
  - RegisterNatives symbool: `_ZN3art3JNIILb0EE15RegisterNativesE…` (via
    enumerateSymbols, niet enumerateExports).

## HET COMMANDO-FRAME (de "lijst met waarden")
`BTLEDataType` enum (decompiled.js ~1591565): AuthRequest=0, AuthResponse=1,
AuthOK=2, WiFiScanRequest=3, WiFiScanRequestDone=4, WiFiScanResult=5,
WiFiJoinRequest=6, WiFiJoinStatus=7, GrillStatusRequest=8, GrillStatusResponse=9,
**GrillCommand=10**, GrillInfoRequest=11, GrillInfoResponse=12, Unknown=255.
Een cook-commando = GrillCommand(10) + payload. JS bouwt dit frame en geeft het
+ device key aan native `GrillCoreRN.encryptData`. Zodra we een 48B-plaintext
hebben, leg 'm hier naast om opcode/setpoint te herkennen.

## WIRE-PROTOCOL (bevestigd via logcat)
- Cook-commando = **2× 48B GATT-write naar b002** (handle 0x0011), via de Android
  `BluetoothGatt` Java-API (react-native-ble-manager), ALLEEN bij een VERSE
  GATT-connect (challenge-handshake). Temp-wijziging op open verbinding stuurt
  GEEN nieuwe crypto-write (gaat via advert-state).
- **Triggeren van de crypto**: telefoon moet verse connect doen: BT UIT → ~10s
  wachten → BT AAN → app laten verbinden → temp zetten. Dan pas `connected:true`
  + de 48B-writes + de crypto-calls.
- **Grill moet air-gapped zijn** (`connectedToInternet=false`): als de grill op
  WiFi zit gaat het commando via de CLOUD (SET_Cook_Command), niet via BLE, en
  vuurt de BLE-crypto niet. In logcat checken:
  `connectedToInternet=(true|false), connectedToBluetooth=(true|false)`.
- De app logt in de gepatchte build de wire-ciphertext plaintext:
  `ReactNativeBleManager: Message(48): <hex>` en
  `PAIRING DEBUG encrypt/decrypt data sessionID: <n>`.

## CLOUD (werkt nu — nuttig voor developer, NIET voor eindgebruiker)
- **Login opgelost** (jouw inzicht + coxtor-repo): de app doet NIET directe Ayla
  login, maar **Auth0 password-realm → id_token → Ayla token_sign_in**.
  `tools/ayla_cloud_prototype.py` doet dit nu (200 OK). EU-constants staan in de
  gitignored `ninja_secrets.env` (auth0_base/client_id/audience + app_id/secret).
- `tools/ayla_lan_key.py` haalt de Ayla **`lanip_key`** op (32ch base64) — de
  LAN-crypto root-secret, zelfs met OFFLINE grill (staat in cloud-device-record).
  Zit in `tools/_re_work/ayla_lan_dump.json`. Het veld heet `lanip_key`, NIET
  `lan_key`.
- `device_key: 3855390` in Ayla-properties = integer device-ID (VALSE VRIEND),
  NIET de crypto-sleutel.
- AWS device-gateway (SigV4-signed): een `<host>/householdsEndUser/…` endpoint
  (host in .env) — vereist AWS SigV4 signing, niet enkel api-key. household_id +
  okta_user_id staan in .env. s3-sts gateway + api_key ook. De BLE Device_Key
  komt hier VERSLEUTELD door en wordt native ontsleuteld — niet als platte waarde.

## UITGESLOTEN / DOODLOPEND (niet opnieuw proberen)
- Statische JS-key `sharkninjawp1000` als wire-crypto → gefalsifieerd (probe-key).
- libcrypto/BoringSSL (`EVP_*`, `AES_cbc_encrypt`) → 0 hooks (crypto is pure Rust).
- Java-bridge in de Gadget → DOOD (geen `Java.perform`).
- `extEncryptData`-C-exports voor cook → vuurden niet (maar zie route 3 hierboven).
- Offline Unicorn-emulator van GATT-pad → tokio async-muur. (Nu achterhaald: we
  gebruiken de LIVE sync-pad-hook i.p.v. offline replay.)
- De 6 gevangen session-keys × alle IV-schema's → ontsleutelen de 48B wire NIET.

## SOLVERS (klaar, wachten op de juiste tuple)
`tools/crypto_puzzle/`:
- `cipher_solver.py` — gegeven (key, cipher, plaintext) vindt AES-mode/IV. We
  WETEN al dat het AES-256-CBC is; dit valideert de exacte IV-plaatsing.
- `derive_solver.py` — vindt een KDF `f(device_key, challenge) → key`. WAARSCHIJNLIJK
  NIET NODIG: de command-key `<internal-key>` bleek STATISCH per grill (overleeft
  reconnect). Als de 48B-key ook statisch is, sla je 'm gewoon één keer op in HA
  (geen KDF, net als coxtor's credential-extractie).
- `_fixtures_data.json` (gitignored) — 17 sessies ciphertext + 1 b004-paar.

## BELANGRIJKE FRIDA-SCRIPTS (gecommit)
- `tools/frida_hook_cbc.js` / `frida_hook_cbc2.js` — CBC-encrypt capture (key+IV
  werken; buffer-labels waren omgedraaid — decrypt("pt")==("ct")).
- `tools/frida_hook_wire.js` — CBC met correcte out-Vec-lezing, filtert op 48B.
- `tools/frida_hook_kdf.js` — session-key + key/IV capture (bewees key statisch).
- `tools/frida_hook_encfn.js` / `encsite*.js` — de site-hooks op 0x1335e0.
- `tools/frida_hook_cbc.js` is het schoonste startpunt om aan te passen.

## GITIGNORED WERKDATA (niet in repo, kan verlopen; regenereerbaar)
`tools/_re_work/`: de `.so`, decompiled.js (77MB), disasm.hasm, alle agent-
rapporten (js_ble_crypto_report, encrypt_fn_report, aes_call_report),
CRYPTO_SOLVED.md, wire_capture.json, ayla_lan_dump.json. `ninja_secrets.env` in
repo-root (Ayla + AWS + Auth0 secrets, wachtwoord ingevuld).

## NOOIT COMMITTEN
Device MAC (`<GRILL_MAC>`), DSN (`SND…`), tokens/id_tokens, household_id,
okta_user_id, de `.so`, captures, session-keys. `tools/_re_work/` en
`ninja_secrets.env` zijn gitignored — houden zo.

## AANBEVOLEN VOLGORDE VOLGENDE SESSIE
1. App-status checken (misschien opnieuw koppelen na de verbindingsproblemen).
   Grill AIR-GAPPED zetten (WiFi eraf) zodat commando's via BLE gaan.
2. (agent, offline) Traceer in de `.so` welke fn de 48B b002-buffer bouwt vlak
   vóór de GATT-write — dat is het 48B-encrypt-punt. Levert hook-offset + welke
   register de key is.
3. (telefoon) Hook dat punt, verse connect + temp, vang (key, iv, 48B ct, pt).
4. (offline) CBC-decrypt de 48B → commando-frame; valideer tegen BTLEDataType.
   Herimplementeer in pure Python → bleak-client → HA. Air-gapped besturing werkt.
