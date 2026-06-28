#!/bin/bash
#
# Maakt een verse HCI snoop capture en haalt hem op van de telefoon.
# Voer dit uit NA elke grill-actie zodat je een set captures opbouwt.
#
# Gebruik:
#   bash capture_btsnoop.sh <label>
# Bijvoorbeeld:
#   bash capture_btsnoop.sh idle
#   bash capture_btsnoop.sh preheat-200
#

LABEL="${1:-capture}"
TS=$(date +%Y%m%d-%H%M%S)
OUT="$HOME/Downloads/ninja_captures"
mkdir -p "$OUT"

echo "Ophalen van btsnoop log voor: $LABEL"

# Genereer een bugreport (bevat de HCI snoop log)
# Snellere methode: direct het snoop bestand pullen als het beschikbaar is
adb shell "ls -la /data/misc/bluetooth/logs/ 2>/dev/null" || echo "Geen directe toegang, gebruik bugreport"

# Probeer eerst directe pull (werkt op sommige toestellen)
adb pull /data/misc/bluetooth/logs/btsnoop_hci.log "$OUT/btsnoop-$LABEL-$TS.log" 2>/dev/null

if [ -f "$OUT/btsnoop-$LABEL-$TS.log" ]; then
    echo "Direct opgehaald: $OUT/btsnoop-$LABEL-$TS.log"
else
    echo "Directe pull mislukt, genereer bugreport (duurt ~1 min)..."
    adb bugreport "$OUT/bugreport-$LABEL-$TS" 2>/dev/null
    echo "Bugreport opgeslagen. Pak btsnoop eruit met:"
    echo "  unzip -o '$OUT/bugreport-$LABEL-$TS.zip' 'FS/data/misc/bluetooth/logs/btsnoop_hci.log' -d '$OUT/extracted-$LABEL'"
fi

echo ""
echo "Klaar voor: $LABEL"
