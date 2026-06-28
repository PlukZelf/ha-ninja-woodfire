"""Constants for the Ninja Woodfire integration."""

DOMAIN = "ninja_woodfire"

# Advertised name prefix
BLE_NAME_PREFIX = "NCEU"

# GATT UUIDs
NINJA_SERVICE_UUID = "0000fcbb-0000-1000-8000-00805f9b34fb"
NINJA_READ_UUID = "0000b001-0000-1000-8000-00805f9b34fb"
NINJA_WRITE_UUID = "0000b002-0000-1000-8000-00805f9b34fb"
NINJA_NOTIFY_UUID = "0000b003-0000-1000-8000-00805f9b34fb"
NINJA_INDICATE_UUID = "0000b004-0000-1000-8000-00805f9b34fb"

# Config entry keys
CONF_ADDRESS = "address"
CONF_NAME = "name"

# Update interval fallback (seconds) — device pushes notifications so this is a heartbeat only
UPDATE_INTERVAL = 30

# Payload length expected from the indicate characteristic
INDICATE_PAYLOAD_LEN = 64

# Coordinator data keys
KEY_RAW_INDICATE = "raw_indicate"
KEY_RAW_NOTIFY = "raw_notify"
KEY_CONNECTED = "connected"
