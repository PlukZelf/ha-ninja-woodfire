#!/bin/bash
#
# All-in-one script: vindt en patcht Frida-detectie + signature check,
# herbouwt de APK, signeert en installeert hem.
#
# Gebruik:
#   cd ~/Downloads/ninja_extracted
#   bash bypass_frida_detection.sh
#
# Vereist: apktool, zipalign, apksigner, adb, ~/ninja.keystore, java
#

set -e

export PATH="$PATH:$HOME/android-build-tools/android-14"

DECODED="ninja_decoded"
PKG="com.sharkninja.ninja.connected.kitchen"
KEYSTORE="$HOME/ninja.keystore"
KS_PASS="ninja123"

echo "=================================================="
echo " Ninja Frida-detectie + signature bypass"
echo "=================================================="
echo ""

# ---------------------------------------------------------------------------
# Stap 1: zoek Frida-detectie in MainActivity en GrillCore
# ---------------------------------------------------------------------------
echo "[1/6] Zoeken naar Frida/anti-tamper detectie..."

MAIN_ACT="$DECODED/smali_classes2/com/sharkninja/ninja/connected/kitchen/MainActivity.smali"

python3 << 'PYEOF'
import re, glob, os

# Patronen die wijzen op detectie van instrumentatie
patterns = [
    'frida', 'gadget', 'tracerpid', 'ptrace', 'xposed', 'substrate',
    'magisk', 'rootbeer', 'isdebugger', 'detectdebug', 're.frida',
    '27042',   # standaard frida poort
    'linjector', 'gum-js-loop', 'frida-server',
]

hits = {}
for smali in glob.glob('ninja_decoded/smali*/**/*.smali', recursive=True):
    try:
        with open(smali, errors='ignore') as f:
            content = f.read().lower()
    except Exception:
        continue
    for p in patterns:
        if p in content:
            hits.setdefault(smali, set()).add(p)

if hits:
    print("  Mogelijke detectie gevonden in:")
    for f, ps in sorted(hits.items()):
        # Sla bekende false positives over
        if 'HermesSamplingProfiler' in f or '/R$' in f:
            continue
        print(f"    {f}")
        print(f"      patronen: {', '.join(sorted(ps))}")
    # Schrijf naar bestand voor stap 2
    with open('/tmp/frida_hits.txt', 'w') as out:
        for f, ps in hits.items():
            if 'HermesSamplingProfiler' in f or '/R$' in f:
                continue
            out.write(f + "\n")
else:
    print("  Geen duidelijke Frida-detectie patronen gevonden.")
    open('/tmp/frida_hits.txt', 'w').close()
PYEOF

echo ""

# ---------------------------------------------------------------------------
# Stap 2: toon de relevante strings/methodes voor handmatige inspectie
# ---------------------------------------------------------------------------
echo "[2/6] Relevante detectie-strings in MainActivity:"
if [ -f "$MAIN_ACT" ]; then
    grep -niE "frida|gadget|tracerpid|ptrace|detect|tamper|debugger|root" "$MAIN_ACT" | head -20 || echo "  (geen treffers in MainActivity)"
else
    echo "  MainActivity.smali niet gevonden!"
fi
echo ""

# ---------------------------------------------------------------------------
# Stap 3: patch detectie-methodes
# We zoeken methodes die een boolean teruggeven en detectie-strings bevatten,
# en forceren ze om altijd false (0x0) terug te geven.
# ---------------------------------------------------------------------------
echo "[3/6] Patchen van detectie-methodes..."

python3 << 'PYEOF'
import re

files_to_check = []
try:
    with open('/tmp/frida_hits.txt') as f:
        files_to_check = [l.strip() for l in f if l.strip()]
except FileNotFoundError:
    pass

# Detectie-strings die in een methode duiden op een check
detect_markers = [
    'frida', 'gadget', '27042', 'tracerpid', 'ptrace',
    'xposed', 'substrate', 'magisk', 'linjector', 'gum-js-loop',
]

patched_methods = 0

for path in files_to_check:
    try:
        with open(path, errors='ignore') as f:
            lines = f.readlines()
    except FileNotFoundError:
        continue

    # Vind methode-grenzen
    i = 0
    out = list(lines)
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('.method'):
            # Verzamel de methode
            start = i
            method_lines = []
            j = i
            while j < len(lines) and not lines[j].strip().startswith('.end method'):
                method_lines.append(lines[j])
                j += 1
            method_body = ''.join(method_lines).lower()

            # Bevat deze methode detectie-markers EN geeft een boolean terug?
            has_marker = any(m in method_body for m in detect_markers)
            returns_bool = ')Z' in method_lines[0]

            if has_marker and returns_bool:
                # Vervang de body door: return false
                signature = method_lines[0]
                # Bepaal .locals/.registers regel behouden
                indent = '    '
                new_method = [signature]
                new_method.append(indent + '.locals 1\n')
                new_method.append(indent + 'const/4 v0, 0x0\n')
                new_method.append(indent + 'return v0\n')
                # Vervang in out
                # Zoek opnieuw de exacte positie in out
                out_start = None
                for k in range(len(out)):
                    if out[k] is lines[start]:
                        out_start = k
                        break
                # Simpeler: markeer en herbouw later
                patched_methods += 1
                print(f"    Patch: {path}")
                print(f"           {signature.strip()}")
                # Voer de vervanging uit op regelniveau
                for k in range(start, j):
                    lines[k] = None  # markeer voor verwijdering
                lines[start] = ''.join(new_method)
            i = j + 1
        else:
            i += 1

    # Schrijf terug (filter None)
    new_lines = [l for l in lines if l is not None]
    with open(path, 'w') as f:
        f.writelines(new_lines)

print(f"\n  Totaal gepatchte detectie-methodes: {patched_methods}")
if patched_methods == 0:
    print("  Geen boolean detectie-methodes gevonden om te patchen.")
    print("  De detectie kan native zijn (in de .so) of obfuscated.")
PYEOF

echo ""

# ---------------------------------------------------------------------------
# Stap 4: herbouw de APK
# ---------------------------------------------------------------------------
echo "[4/6] APK herbouwen..."
rm -f ninja_patched.apk ninja_patched_aligned.apk
apktool b "$DECODED" -o ninja_patched.apk 2>&1 | tail -3
echo ""

# ---------------------------------------------------------------------------
# Stap 5: zipalign + signeren
# ---------------------------------------------------------------------------
echo "[5/6] Zipalign + signeren..."
zipalign -f 4 ninja_patched.apk ninja_patched_aligned.apk
apksigner sign --ks "$KEYSTORE" \
  --ks-key-alias ninja \
  --ks-pass pass:$KS_PASS \
  --key-pass pass:$KS_PASS \
  ninja_patched_aligned.apk
echo "  Gesigneerd."
echo ""

# ---------------------------------------------------------------------------
# Stap 6: installeren
# ---------------------------------------------------------------------------
echo "[6/6] Installeren op telefoon..."
adb uninstall "$PKG" 2>/dev/null || echo "  (app was niet geinstalleerd)"

# Zorg dat de config splits ook gesigneerd zijn met dezelfde key
for split in config.arm64_v8a.apk config.en.apk config.xhdpi.apk; do
    if [ -f "$split" ]; then
        apksigner sign --ks "$KEYSTORE" \
          --ks-key-alias ninja \
          --ks-pass pass:$KS_PASS \
          --key-pass pass:$KS_PASS \
          "$split" 2>/dev/null || true
    fi
done

adb install-multiple \
  ninja_patched_aligned.apk \
  config.arm64_v8a.apk \
  config.en.apk \
  config.xhdpi.apk

echo ""
echo "=================================================="
echo " Klaar!"
echo "=================================================="
echo ""
echo "Volgende stappen:"
echo "1. Open de Ninja app op je telefoon"
echo "2. Als hij blijft draaien (niet crasht):"
echo "   frida-ps -U | grep -i ninja"
echo "3. Attach de hook:"
echo "   frida -U -n NinjaProConnect -l ~/ninja_hook.js"
echo ""
echo "Als de app nog steeds crasht bij Frida attach, dan zit de"
echo "detectie in de native library (.so) en moeten we een andere"
echo "aanpak nemen (native hooking of LD_PRELOAD)."
