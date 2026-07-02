"""Constants for the Ninja Woodfire integration."""

DOMAIN = "ninja_woodfire"

# Advertised name prefix
BLE_NAME_PREFIX = "NCEU"

# GATT UUIDs
NINJA_SERVICE_UUID = "0000fcbb-0000-1000-8000-00805f9b34fb"

# Advertisement company id (both grill AD structures use this).
COMPANY_ID = 0x0C4F

# Config entry keys
CONF_ADDRESS = "address"
CONF_NAME = "name"

# Update interval fallback (seconds) — device pushes notifications so this is a heartbeat only
UPDATE_INTERVAL = 30
