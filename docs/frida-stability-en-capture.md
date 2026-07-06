# Frida-instabiliteit: diagnose + capture-plan (2026-07-06)

Doel van dit doc: de gepatchte-app-instabiliteit uit de handoff omzeilen, en in
**één sessie zonder her-attachen** het Fase-2-sleutelmateriaal vangen dat de
`crypto_puzzle`-solvers nodig hebben.

## Diagnose van de instabiliteit

Symptoom (handoff): de gepatchte Frida-Gadget-app hangt op logo / freezet /
degradeert na ~5-7 attach-cycli. Origineel app is stabiel maar heeft geen Frida.

Oorzaak (hoogst waarschijnlijk): **herhaald attach/detach op een Gadget-build**.
- `tools/frida_run.py` doet elke run een verse `device.attach("Gadget")`. Frida
  Gadget is ontworpen om ÉÉN script bij app-start te laden, niet om er live in-
  en uit te koppelen. Elke attach/detach-cyclus laat rommel achter (hooks,
  Interceptor-trampolines, JS-heap); na een paar cycli is de app-state kapot.
- De GATT-crypto draait bovendien op een tokio async-runtime (bewezen doodlopend
  offline). Live Interceptor-trampolines midden in async executor-frames
  vergroten de kans op corruptie/crash.

## De drie regels die de instabiliteit vermijden

1. **Nul her-attach per sessie.** Attach één keer, vang alles in één run, sluit
   dan pas af. Geen 5-7 cycli meer.
2. **Zelf-voltooiend script.** Zodra de tuple compleet is, schrijft het script
   `_keymat.json` + `_cipherpair.json` en meldt "DONE" — jij hoeft niet te
   itereren of te gokken wanneer je klaar bent.
3. **Passief observeren, niet muteren.** Alleen lezen (key/IV/CT/PT uit
   argumenten), geen `.replace()` / geen retval-patching. Passief observeren
   tijdens de app z'n EIGEN decrypt werkte eerder wél (geen async-abort).

## Aanbevolen injectie-volgorde (meest → minst stabiel)

A. **frida-server op geroote telefoon** (indien mogelijk): `frida -U -f <pkg>
   -l script.js` met spawn-gating. Verreweg het stabielst; geen Gadget-rommel.
   Pixel 7a is niet geroot -> waarschijnlijk niet beschikbaar.

B. **Gadget met spawn-gate (huidige route, verbeterd):** laad het hookscript dat
   in de Gadget-config als `path` staat, zodat het bij app-start meelaadt vóór
   de crypto-init. Start de app VERS (force-stop eerst), doe de hele capture in
   die ene levensduur, kill daarna de app. Nooit live her-attachen.
   - Force-stop vooraf zodat je met schone state begint.
   - `frida_run.py` blijft bruikbaar voor de eerste attach, maar draai het
     capture-script maar ÉÉN keer per app-start.

## Wat het capture-script moet doen (zie tools/frida_capture_session.js)

In één app-levensduur, tijdens één connect+commando in de app, vangen:

| veld | bron | hoe |
|---|---|---|
| challenge (20B) | wire / decrypt-context | al plaintext; komt binnen bij eerste crypto-call |
| raw session_key (32B) | AES-core / cipher-init | lees het key-argument bij de AES-CBC core (`0x1760c8`) — de crux |
| cipher + plaintext | extDecryptData (b004) of AES-core in/out | in- en uitbuffer van dezelfde call |
| Device_Key | apart, via cloud | `tools/aws_device_key.py` (read-only GET) — NIET via Frida |

Belangrijk uit eerdere sessies:
- De JNI-exports (`extEncryptData` etc.) VUREN NIET voor het temp-commando (dat
  gaat via interne Rust `Cook.extSetTemp`). Daarom is de **AES-core-hook op
  offset `0x1760c8`** het juiste aangrijppunt, niet de JNI-laag.
- Deze Gadget blokkeert de Java-bridge en `setTimeout/setInterval` vuren niet in
  z'n JS-runtime -> geen polling-loops, alleen native Interceptor.
- Device_Key komt NIET via Frida maar via de cloud (aws_device_key.py). De hook
  levert de andere drie velden; de solver bevestigt dan
  `f(Device_Key, challenge) -> session_key`.

## Draaien

```
# 1. (eenmalig, los) Device_Key ophalen
python tools/aws_device_key.py key <DSN>

# 2. app force-stoppen, dan vers starten met de Gadget-injectie
# 3. capture-script draaien (ÉÉN keer), dan in de app: connect + zet temp
python tools/frida_run.py tools/frida_capture_session.js

# script schrijft _keymat.json + _cipherpair.json en print DONE
# 4. solvers draaien (offline)
python tools/crypto_puzzle/derive_solver.py
python tools/crypto_puzzle/cipher_solver.py
```
