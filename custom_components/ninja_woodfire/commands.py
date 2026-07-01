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

# Probe-driven vs. time-driven cooking.
COOK_TYPES: tuple[str, ...] = ("Timed", "Probe")

# Wood/pellet flavors. TODO: confirm the exact option set the device accepts.
WOOD_FLAVORS: tuple[str, ...] = ("Robust", "Rich", "Savory")

# Temperature and time limits. TODO: confirm real per-mode limits from the app.
MIN_TEMP_C = 40
MAX_TEMP_C = 260
MIN_COOK_MINUTES = 1
MAX_COOK_MINUTES = 1440


class CommandNotSupported(RuntimeError):
    """Raised when a command cannot be built yet (protocol not confirmed)."""


_PENDING = "command payload format not yet reverse-engineered (see ROADMAP.md)"


def set_cook_mode(mode: str) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_cook_type(cook_type: str) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_wood_flavor(flavor: str) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_target_temp(celsius: int) -> bytes:
    raise CommandNotSupported(_PENDING)


def set_cook_time(minutes: int) -> bytes:
    raise CommandNotSupported(_PENDING)


def start_cook() -> bytes:
    raise CommandNotSupported(_PENDING)


def stop_cook() -> bytes:
    raise CommandNotSupported(_PENDING)
