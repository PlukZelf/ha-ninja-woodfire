"""Command payload builders for the Ninja Woodfire.

The command (write) payload format is NOT yet confirmed — it depends on the
protocol work still in progress (see ROADMAP.md). Until the format is known,
every builder raises :class:`CommandNotSupported` so we never write unverified
bytes to a real appliance. The control entities are wired up and functional
from the UI side; the moment the format is reverse-engineered, filling in
these builders is all that's needed to make them live.
"""

from __future__ import annotations

# Cook functions as reported by the device (see protocol.py). "AirCrisp" is
# shown as "Air Fry" in the Ninja app.
COOK_MODES: tuple[str, ...] = (
    "Grill",
    "Smoke",
    "AirCrisp",
    "Roast",
    "Bake",
    "Broil",
    "Dehydrate",
    "MaxRoast",
    "SlowCook",
)

# Default cook function when the device has not reported one yet.
DEFAULT_COOK_MODE = "Grill"

# Probe-driven vs. time-driven cooking.
COOK_TYPES: tuple[str, ...] = ("Timed", "Probe")

# Temperature and time limits. TODO: confirm real per-mode limits from the app.
MIN_TEMP_C = 40
MAX_TEMP_C = 260
MIN_COOK_MINUTES = 0
MAX_COOK_MINUTES = 1440


# =============================================================================
# TEMPORARY / STUB BEHAVIOR — REMOVE ONCE DECODING WORKS
# -----------------------------------------------------------------------------
# The write payload format is not reverse-engineered yet, so no command can
# actually reach the grill. To let the UI be used and demoed in the meantime,
# the control entities run in OPTIMISTIC mode: setting a value updates only the
# local Home Assistant state, nothing is transmitted.
#
# When the command protocol is confirmed:
#   1. Fill in the builder functions below with the real payload bytes.
#   2. Set OPTIMISTIC_CONTROLS = False so entities reflect the device's actual
#      reported state instead of the locally-remembered value.
# Search the codebase for OPTIMISTIC_CONTROLS to find every spot that depends
# on this flag.
# =============================================================================
OPTIMISTIC_CONTROLS = True


class CommandNotSupported(RuntimeError):
    """Raised when a command cannot be built yet (protocol not confirmed)."""


_PENDING = "command payload format not yet reverse-engineered (see ROADMAP.md)"


def set_cook_mode(mode: str) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_cook_type(cook_type: str) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_wood_flavor(enabled: bool) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_probe1_target_temp(celsius: int) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_probe2_target_temp(celsius: int) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_cook_time(minutes: int) -> bytes:
    raise CommandNotSupported(_PENDING)


def start_cook() -> bytes:
    raise CommandNotSupported(_PENDING)


def stop_cook() -> bytes:
    raise CommandNotSupported(_PENDING)
