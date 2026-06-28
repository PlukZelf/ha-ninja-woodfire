#!/bin/bash
# Script om alle integratie bestanden naar GitHub te pushen
# Uitvoeren in de root van je lokale ha-ninja-woodfire repo

set -e

REPO_DIR="${1:-$(pwd)}"
echo "Werken vanuit: $REPO_DIR"

# Kopieer custom_components
mkdir -p "$REPO_DIR/custom_components/ninja_woodfire/lib"
mkdir -p "$REPO_DIR/.github/workflows"

# Functie om een bestand te kopiëren als het bestaat
copy_if_exists() {
    local src="$1"
    local dst="$2"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "✓ $dst"
    else
        echo "⚠ Niet gevonden: $src"
    fi
}

OUTPUTS_DIR="$(dirname "$0")"

# Root bestanden
copy_if_exists "$OUTPUTS_DIR/README.md"     "$REPO_DIR/README.md"
copy_if_exists "$OUTPUTS_DIR/hacs.json"     "$REPO_DIR/hacs.json"
copy_if_exists "$OUTPUTS_DIR/ENVIRONMENT.md" "$REPO_DIR/ENVIRONMENT.md"
copy_if_exists "$OUTPUTS_DIR/AGENT_HANDOVER.md" "$REPO_DIR/AGENT_HANDOVER.md"

# GitHub Actions
copy_if_exists "$OUTPUTS_DIR/.github/workflows/release.yml"  "$REPO_DIR/.github/workflows/release.yml"
copy_if_exists "$OUTPUTS_DIR/.github/workflows/validate.yml" "$REPO_DIR/.github/workflows/validate.yml"

# Integratie bestanden
INTEGRATION="$OUTPUTS_DIR/custom_components/ninja_woodfire"
DEST="$REPO_DIR/custom_components/ninja_woodfire"

for f in __init__.py manifest.json config_flow.py const.py coordinator.py \
          bluetooth.py protocol.py grillcore_native.py sensor.py \
          binary_sensor.py diagnostics.py; do
    copy_if_exists "$INTEGRATION/$f" "$DEST/$f"
done

# Translations
mkdir -p "$DEST/translations"
copy_if_exists "$INTEGRATION/translations/nl.json" "$DEST/translations/nl.json"
copy_if_exists "$INTEGRATION/translations/en.json" "$DEST/translations/en.json"

# Lib
copy_if_exists "$INTEGRATION/lib/README.md"   "$DEST/lib/README.md"
touch "$DEST/lib/.gitkeep"

echo ""
echo "Alle bestanden gekopieerd. Nu committen en pushen:"
echo ""
echo "  cd $REPO_DIR"
echo "  git add -A"
echo "  git status"
echo "  git commit -m 'feat: add HA integration, GitHub Actions, and protocol research'"
echo "  git push origin main"
echo ""
echo "Voor een beta release:"
echo "  git tag v0.1.0-beta.1"
echo "  git push origin v0.1.0-beta.1"
