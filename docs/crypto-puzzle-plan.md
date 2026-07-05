# Plan: GATT-commando-crypto oplossen als OFFLINE PUZZEL

**Kernidee (de reframe):** niet de sleutel/het algoritme uit de app *stelen*
(geheugen, hooks, statische RE — allemaal doodgelopen), maar de crypto
*oplossen* als een cryptografische puzzel met grondwaarheid-data die we al
hebben + één keer de ontbrekende sleutel. De afleiding is vrijwel zeker een
**standaard constructie** (HMAC/HKDF/AES/SHA), geen exotische magie.

**Doel:** in pure Python een b002-commando kunnen bouwen+versleutelen zodat HA
lokaal de grill bestuurt. Grill nooit online, geen app/telefoon bij eindgebruik.

---

## Bewezen feiten (basis)
- b002-write (48B) = **versleuteld** (bewezen: geen structuur, geen nul-padding,
  ~max entropie, twee commando's delen 0 bytes). Wire-framing:
  `CCCD 0x0017←02 00` → grill stuurt **20B challenge** (h=0x0016) → app stuurt
  **48B** (h=0x0011): eerst auth-response, dan commando('s).
- Sleutel is **per-sessie**, afgeleid van een per-apparaat **Device_Key** +
  de 20B challenge. Device_Key komt **versleuteld** uit de Ayla/AWS-cloud,
  wordt native ontsleuteld, **niet op schijf bewaard** (RKStorage leeg).
- b004-state (64B) wordt met dezelfde sessie-sleutel ontsleuteld → 47B plaintext.

## Grondwaarheid die we AL hebben (fixtures)
- `captures/btsnoop-setcmd-last.log` (gitignored): ~15 sessies met
  (challenge_20B, 48B-writes) — challenge is **leesbaar**, rest ciphertext.
- Verse capture van vandaag: 1 sessie (challenge + 2×48B command-writes),
  temp=40/dehydrate bevestigd door grill.
- 1 b004-paar (van eerdere Frida JNI-hook): **cipher 64B → plaintext 47B**
  (scratchpad `gatt_capture_1.txt`).
- Bekende command-JSON-vorm (`{"cmd":...,"data":[...]}`) en de ProbeProtocol
  frame-structuur (header+opcode+temp×10+checksum) — als *orakel* voor "ziet
  ontsleutelde output er zinnig uit?".

## Wat ONTBREEKT (de enige echte gaten)
1. De **Device_Key** (één keer, per apparaat).
2. Voor **één** sessie: de **rauwe sessie-sleutel** (de AES-sleutel die de app
   gebruikt), naast de challenge en een cipher↔plaintext-paar.
Met #1 + #2 wordt de afleiding `f(Device_Key, challenge) → sessie_sleutel` een
klein, offline oplosbaar raadsel (standaard-KDF's uitproberen).

---

## Fasen (met validatie-poorten)

### Fase 1 — Puzzel-fundament (OFFLINE, delegeerbaar aan agent)
- Verzamel álle grondwaarheid in één schone, gedocumenteerde fixtures-map
  (btsnoop-tuples geparsed, b004-paar, JSON-vormen, gevonden statische keys).
- Bouw een **hypothese-tester** (skeleton): gegeven een kandidaat-sessie-sleutel
  + een (cipher,plaintext)-paar → test AES-modi (CBC/CTR/GCM, IV-plaatsingen)
  en meld welke correct ontsleutelt. En: gegeven (Device_Key, challenge,
  sessie_sleutel)-tuples → test standaard-afleidingen (HMAC-SHA256, HKDF,
  AES-ECB/CBC, SHA256(K‖C), truncaties) tot `f` de sleutel reproduceert.
- Documenteer **exact** welke captures Fase 2 moet opleveren.
- **Poort:** harness draait, laadt fixtures, en print duidelijk "wacht op
  sleutelmateriaal" (faalt netjes, geen crash).

### Fase 2 — Ontbrekende grondwaarheid vangen (TELEFOON, interactief: ik+jij)
- Eén schone sessie waarin we vangen: Device_Key, challenge, **rauwe
  sessie-sleutel** (uit `Aes256::new`-arg óf via de b004-decrypt), en een
  matched cipher↔plaintext. Dit is het lastige stuk, maar we hoeven het maar
  **één keer** te doen (daarna is alles offline).
- **Poort:** ≥1 volledig tuple `(Device_Key, challenge, sessie_sleutel,
  cipher, plaintext)` op schijf.

### Fase 3 — Afleiding oplossen (OFFLINE, agent)
- Draai de hypothese-tester op de tuples → vind `f`. Valideer tegen álle
  btsnoop-sessies (elke challenge → afgeleide sleutel → ontsleutelt naar
  herkenbare command-structuur).
- **Poort:** `derive_key(Device_Key, challenge)` reproduceert elk gevangen paar.

### Fase 4 — Pure-Python crypto (OFFLINE, agent)
- `encrypt_command` / `decrypt_state` die byte-voor-byte matchen met grondwaarheid.
- **Poort:** round-trip klopt op alle fixtures.

### Fase 5 — Client + HA
- bleak-client (connect→challenge→auth→commando) en HA control-entities.

---

## PARALLEL SPOOR — Ayla LAN-mode (OFFLINE onderzoek, agent)
Deze grill zit op **Ayla** (`ads-eu.aylanetworks.com`). Ayla-apparaten hebben
een **gedocumenteerde LAN-mode**: de app praat lokaal rechtstreeks met het
apparaat via een LAN-sleutel, zónder cloud. Het `DEVICE_KEY` /
`getReconnectWifiDeviceKey` / `lan_ip` / `lan_enabled`-materiaal dat we zagen is
exact Ayla's LAN-sleuteluitwisseling. Ayla's LAN-crypto is **openbaar**.
- Onderzoek: ondersteunt dit apparaat LAN-mode? Wat is de gedocumenteerde
  sleuteluitwisseling + crypto? Kan HA de grill zo lokaal besturen (evt. over
  lokale WiFi zonder internet) i.p.v. de BLE-crypto te kraken?
- Dit kan de héle BLE-puzzel overbodig maken als het van toepassing is.

---

## Regels (om op-plan te blijven)
- Eén fase per agent; poort = klaar. Geen aannames, wél bewijs met echte bytes.
- Nooit MAC/DSN/Device_Key/tokens committen (gitignored fixtures).
- Niet opnieuw: geheugen-string-scan (leeg), lokale opslag (leeg), JNI-hook
  (vuurt niet), offline emulator (async-muur). Die zijn uitgeput.
