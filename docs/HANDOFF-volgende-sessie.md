# OVERDRACHT — volgende sessie (2026-07-05)

Lees dit eerst. Daarna `docs/crypto-puzzle-plan.md` (het plan) en de scratchpad-
rapporten hieronder. Doel: **HA stuurt lokaal commando's naar de Ninja Woodfire
grill** (lezen werkt al & is geshipped; dit gaat puur over SCHRIJVEN/besturen).

## HARDE EIS VAN DE GEBRUIKER (niet onderhandelbaar)
- De **eindgebruiker** van de HA-integratie mag de grill **NIET op WiFi/internet**
  hoeven zetten. Gebruiker gebruikt de grill via **BLE**, air-gapped.
- **De ONTWIKKELAAR (jij/gebruiker nu) MAG de grill wél tijdelijk op WiFi zetten**
  om iets te reverse-engineeren. Dat onderscheid is cruciaal (zie hieronder).

## WAT BEWEZEN IS (hard, met bytes)
- BLE-commando (48B write naar char b002, handle 0x0011) is **versleuteld**:
  geen structuur, geen nul-padding, ~max entropie, 2 commando's delen 0 bytes.
  Wire-flow: `CCCD 0x0017 <- 02 00` -> grill stuurt **20B challenge** (h=0x0016)
  -> app stuurt **48B** (h=0x0011): eerst auth-response, dan commando('s).
- Sessie-sleutel is **per-sessie**, afgeleid van een per-apparaat **Device_Key**
  + de 20B challenge. Device_Key: niet op schijf (RKStorage leeg), komt
  versleuteld uit cloud, native ontsleuteld, alleen kort in RAM.
- GATT gebruikt NIET de advert-key (getest, faalt). NIET libcrypto (0 hooks).

## DOODLOPENDE WEGEN (NIET opnieuw proberen — uitgeput)
- **Statische JS-sleutel `sharkninjawp1000` als wire-crypto -> GEFALSIFICEERD
  (2026-07-06).** De RN-bundle bevatte een statische AES-128-CBC
  (key=`sharkninjawp1000`, iv=`1234567890abcdef`), zie `STATIC_KEY_FOUND.md`.
  Offline getest met `tools/crypto_puzzle/static_key_test.py` tegen het b004-
  paar (bekende plaintext): reproduceert de plaintext NIET, alle 34 command-
  writes -> garbage. Dit is de **probe-accessoire-crypto**, niet de grill-
  command-crypto. Er zit een native per-sessie laag omheen (bevestigt de
  max-entropie/0-gedeelde-bytes-observatie). NIET opnieuw proberen.
- **coxtor/ninja-woodfire-integration bekeken (2026-07-06) -> geen BLE-hulp.**
  Is 100% de cloud-route die wij al hebben (platte JSON naar Ayla
  `SET_Cook_Command`, nul crypto). De `device_key` die het meestuurt is een
  cloud device-ID-**integer** in de payload, NIET onze BLE-`Device_Key` (valse
  vriend). Enige mogelijk-nuttige restje: hun `scripts/extract_credentials.py`
  is een kant-en-klare logcat-regex voor de 4 app-globale cloud-identifiers
  (ayla_app_id/secret, auth0_client_id/audience) als die ooit roteren — reserve,
  niet op het kritieke pad.
- Geheugen-string-scan op "DEVICE_KEY" -> leeg.
- Lokale opslag (RKStorage/MMKV) lezen -> sleutel staat er niet.
- JNI-hook op extEncryptData/extSendBTPayload -> vuurt niet voor temp-commando
  (gaat via interne Rust `Cook.extSetTemp`, niet via die JNI-exports).
- Offline Unicorn-emulator van GATT-pad -> tokio async-muur ("async function in
  non async context").
- Statische RE van RN JS-bundle voor BLE-crypto -> die JS is de CLOUD-laag, geen
  BLE-crypto erin.
- Gepatchte Frida-Gadget-app is INSTABIEL (hangt op logo, freezet, degradeert na
  ~5-7 attach-cycli). Origineel app werkt betrouwbaar maar heeft geen Frida.

## TWEE LEVENDE SPOREN (kies/combineer)

### SPOOR 1 — Crypto als PUZZEL oplossen (BLE, air-gapped eindresultaat)
Fase 1 is KLAAR (agent, geverifieerd). `tools/crypto_puzzle/`:
- `fixtures.py` -> **17 sessies** grondwaarheid (17 challenges, 34×48B writes) +
  1 b004-paar (cipher 64B -> plaintext 47B). Data in gitignored
  `_fixtures_data.json`.
- `derive_solver.py` -> test standaard-KDF's (HMAC/HKDF/SHA/AES/XOR) zodra we een
  `(Device_Key, challenge, session_key)`-tuple hebben. Leest `_keymat.json`.
- `cipher_solver.py` -> test AES-modi/IV zodra we `(key, cipher, plaintext)`
  hebben. Leest `_cipherpair.json`.
- Poorten draaien, wachten op sleutelmateriaal.

**FASE 2 = het enige ontbrekende gat (telefoon, ~1 sessie):** vang van EEN sessie:
`(Device_Key, challenge_20B, RAUWE session_key_32B, matched cipher+plaintext)`.
- challenge = al leesbaar op de wire.
- rauwe session_key = hook `Aes256::new`/cipher-init tijdens een IN-CONTEXT
  `extDecryptData`/`extEncryptData` en lees het sleutel-argument. (Passief
  observeren tijdens de app z'n eigen decrypt werkte eerder wél — geen async
  abort.) cipher+plaintext komen uit dezelfde decrypt-hook.
- Zet de 3 hex-waarden in `tools/crypto_puzzle/_keymat.json`
  `{device_key,challenge,session_key}` en `_cipherpair.json`
  `{key,cipher,plaintext}`; draai de solvers -> vindt f offline, valideer tegen
  alle 17 sessies. Daarna Fase 3-5 (pure-Python crypto -> bleak-client -> HA).

### SPOOR 2 — Ayla LAN-mode als SLEUTEL-LEVERANCIER (developer op WiFi)
Rapport: `scratchpad/ayla_lan_research.md`. **VERDICT: MAYBE, crypto is openbaar.**
- Onze eigen capture toont: grill "Rookertje" had `lan_enabled:true`,
  `connection_priority:["LAN"]`, `lan_ip:<GRILL_LAN_IP>`. Dus de grill DRAAIT een
  Ayla LAN-server als 'ie op WiFi zit.
- LAN-crypto is gedocumenteerd + bestaande Python-libs:
  `jakecrowley/AylaLocalAPI` (LAN key-exchange, HMAC-SHA256 KDF, AES-128,
  ondertekende datapoints) + `rewardone/ayla-iot-unofficial` (cloud `lan.json`
  fetch van de `lan_key`).
- LAN werkt over lokale WiFi (na 1x internet voor lan_key). Volledige lokale
  tweerichtings-besturing (incl. commando's) MOGELIJK.

**MAAR LAN kan NIET de eindoplossing zijn** (gebruiker mag geen WiFi). LAN is
alleen nuttig als **REVERSE-ENGINEER-GEREEDSCHAP**:

**DE BESLISSENDE VRAAG voor volgende sessie:** is de Ayla **`lan_key`** dezelfde
als (of afleidbaar naar) de BLE **`Device_Key`**? 
- Als JA -> ontwikkelaar haalt eenmalig via LAN de sleutel, die werkt ook voor
  BLE; eindgebruiker houdt puur BLE. Best of both.
- Als NEE -> LAN en BLE zijn los; ga puur op SPOOR 1 Fase 2.
- ZO TE TESTEN (offline eerst): vergelijk hoe de app de `lan_key` gebruikt vs
  de BLE `Device_Key` (uit `launch-pretty.js`/`snjs-pretty.js` + de `.so`).
  En/of: haal via SPOOR 2 de sleutel op en probeer die in de SPOOR-1 solvers.

## AANBEVOLEN VOLGORDE VOLGENDE SESSIE
(Bijgewerkt 2026-07-06: statische-sleutel-route is dood, zie boven. De twee
sporen hieronder zijn ongewijzigd en nu de enige levende paden.)
1. (offline agent) Toets of `lan_key` == BLE `Device_Key`-bron. Beslist alles.
2. Als gelijk: gebruik LAN (ontwikkelaar, WiFi eenmalig) om sleutel te winnen ->
   voer in SPOOR-1 solvers -> los f op -> pure-Python BLE-besturing.
3. Als niet gelijk: SPOOR 1 Fase 2 (telefoon: rauwe session_key hooken). Dit is
   het meest concrete pad: de solvers staan klaar, alleen 1 sessie sleutel-
   materiaal ontbreekt nog. `tools/aws_device_key.py` levert de Device_Key-helft
   van de tuple (cloud GET, read-only).

## OMGEVING / HANDIGE FEITEN
- Grill MAC `<GRILL_MAC>`, DSN `<DSN>`, naam "Rookertje",
  model OG900-EU. (NIET committen.)
- Telefoon Pixel 7a, niet geroot. Origineel app = betrouwbaar maar geen Frida.
  Gepatchte app `C:/Users/micro/ninja_patched_aligned.apk` = Frida-Gadget maar
  instabiel. Attach: `frida.get_usb_device().attach("Gadget")` (Frida 17: gebruik
  `Process.findModuleByName(x).findExportByName(y)`, NIET `Module.findExportByName`).
- mitmproxy WERKT (SSL-unpinning via native BoringSSL hooks: `SSL_CTX_set_custom_verify`
  + `SSL_get_verify_result`->0). Script: `scratchpad/ssl_unpin.py`. PC-proxy
  `192.168.10.193:8080`. Zo haalden we de cloud-login + AWS-blobs op.
- Cloud: Okta login `logineu.sharkninja.com` (EU), AWS gateway
  `k02lj336p0.execute-api.eu-central-1.amazonaws.com` (x-api-key opgevangen),
  Ayla `ads-eu.aylanetworks.com`. Device_Key komt VERSLEUTELD via `s3-sts/V1`.
- Belangrijke scratchpad-bestanden (buiten repo, kunnen verlopen):
  `mitm_login_complete.jsonl` (volledige cloud-login capture),
  `ayla_lan_research.md`, `crypto_layering_analysis.md`, `js_crypto_reconstruction.md`,
  `send_flow_report.md`, `gatt_capture_1.txt` (b004 paar),
  `btsnoop_extract/*.filtered*` (verse temp=40 capture).
- Bestaande tools: `tools/analyze_ninja_handshake.py` (btsnoop->ATT events,
  env `NINJA_GRILL_MAC`), `tools/crypto_puzzle/*`, `tools/aws_device_key.py`,
  `tools/ayla_cloud_prototype.py`.

## COMMIT-STATUS
- `docs/crypto-puzzle-plan.md`, `docs/HANDOFF-volgende-sessie.md`,
  `tools/crypto_puzzle/*` + `.gitignore` staan UNCOMMITTED (nog niet gecommit).
  Overweeg te committen (ciphertext-data is gitignored). NOOIT MAC/DSN/keys/tokens
  committen.
