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

# Heartbeat interval (seconds): how often the coordinator re-evaluates the
# "recently seen" flag. The grill advertises every few seconds, so a short
# heartbeat keeps the Connected sensor responsive without polling the device.
UPDATE_INTERVAL = 10
