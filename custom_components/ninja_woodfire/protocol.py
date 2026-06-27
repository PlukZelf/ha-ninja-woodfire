"""Protocol layer for Ninja Woodfire Pro Connect XL BLE payloads.

The native library (libgrillcore_android.so) handles decryption.
After decryption, the payload is a structured binary message.

## Known data types (bt_data_type field)
- 10: GrillStatus — full device state
- 16: Command acknowledgement

## GrillState fields (confirmed from logcat GrillState(...) output)
These field names and types are confirmed by intercepting the
parsed output from the native library via Android logcat.

The binary layout of the decrypted payload is not yet fully
documented. This module will be extended as more captures are
analysed. For now, NinjaState stores whatever the native library
returns, and the coordinator passes it to HA entities.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cook mode constants (confirmed from JS bundle and logcat)
# ---------------------------------------------------------------------------

COOK_MODES = {
    0: "NotSet",
    1: "Grill",
    2: "Smoke",
    3: "AirCrisp",
    4: "Roast",
    5: "Bake",
    6: "Broil",
    7: "Dehydrate",
    8: "MaxRoast",
    9: "SlowCook",
}

COOK_STATES = {
    "none": "Idle",
    "idle": "Idle",
    "powered OFF": "Off",
    "Idle": "Idle",
    "Preheating": "Preheating",
    "Cooking": "Cooking",
    "CookComplete": "Complete",
    "Error": "Error",
}

PROBE_STATES = {
    "ProbeNotSet": "NotSet",
    "ProbeActive": "Active",
    "ProbeComplete": "Complete",
}


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProbeState:
    active: bool = False
    plugged_in: bool = False
    desired_temp_c: int = 0
    current_temp_c: int = 0
    state: str = "NotSet"
    cook_progress: int = 0
    resting_progress: int = 0


@dataclass
class NinjaState:
    """Parsed device state from the Ninja Woodfire Pro Connect XL.

    All fields default to safe/unknown values.
    Fields are populated from the GrillState data returned by the
    native library or parsed from decrypted BLE payloads.
    """

    # Raw payloads for diagnostics
    raw_indicate: bytes = field(default=b"", repr=False)
    raw_notify: bytes = field(default=b"", repr=False)

    # Connectivity
    connected: bool = False
    connected_to_internet: bool = False

    # Device state
    state: str = "Unknown"          # Idle, Preheating, Cooking, Complete, Error, Off
    lid_open: bool = False
    wood_fire: bool = False
    error: int = 0

    # Cook settings
    cook_mode: str = "NotSet"       # Grill, Smoke, AirCrisp, Roast, Bake, Broil, Dehydrate
    cook_type: str = "NotSet"       # NotSet, Timed, Probe

    # Oven / grill temperatures
    oven_current_temp_c: int = 0
    oven_desired_temp_c: int = 0
    oven_time_set_s: int = 0
    oven_time_left_s: int = 0
    oven_on: bool = False

    # Progress (0-100)
    ignition_progress: int = 0
    preheat_progress: int = 0
    cook_progress: int = 0
    resting_progress: int = 0

    # Probes
    probe1: ProbeState = field(default_factory=ProbeState)
    probe2: ProbeState = field(default_factory=ProbeState)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_grill_state_json(data: str | bytes) -> NinjaState | None:
    """Parse a JSON GrillState string from the native library callback.

    The native library emits state as JSON when called via the
    GrillManager.extSetStateCallback path. Format matches the
    logcat GrillState(...) output.
    """
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        obj = json.loads(data)
        return _from_dict(obj)
    except (json.JSONDecodeError, KeyError, TypeError) as err:
        _LOGGER.debug("Failed to parse GrillState JSON: %s", err)
        return None


def _from_dict(obj: dict) -> NinjaState:
    """Convert a GrillState dict to NinjaState."""
    state = NinjaState()

    state.state = COOK_STATES.get(obj.get("state", ""), obj.get("state", "Unknown"))
    state.lid_open = bool(obj.get("lidOpen", False))
    state.wood_fire = bool(obj.get("woodFire", False))
    state.cook_mode = obj.get("cookMode", "NotSet")
    state.cook_type = obj.get("cookType", "NotSet")
    state.error = int(obj.get("error", 0))
    state.ignition_progress = int(obj.get("ignitionProgress", 0))
    state.preheat_progress = int(obj.get("preheatProgress", 0))
    state.cook_progress = int(obj.get("cookProgress", 0))
    state.resting_progress = int(obj.get("restingProgress", 0))
    state.connected_to_internet = bool(obj.get("connectedToInternet", False))

    oven = obj.get("oven", {})
    state.oven_on = bool(oven.get("on", False))
    state.oven_current_temp_c = int(oven.get("currentTemp", 0))
    state.oven_desired_temp_c = int(oven.get("desiredTemp", 0))
    state.oven_time_set_s = int(oven.get("timeSet", 0))
    state.oven_time_left_s = int(oven.get("timeLeft", 0))

    for i, attr in enumerate(("probe1", "probe2"), 1):
        p = obj.get(f"probe{i}", {})
        probe = ProbeState(
            active=bool(p.get("active", False)),
            plugged_in=bool(p.get("pluggedIn", False)),
            desired_temp_c=int(p.get("desiredTemp", 0)),
            current_temp_c=int(p.get("currentTemp", 0)),
            state=PROBE_STATES.get(p.get("state", ""), p.get("state", "NotSet")),
            cook_progress=int(p.get("cookProgress", 0)),
            resting_progress=int(p.get("restingProgress", 0)),
        )
        setattr(state, attr, probe)

    return state


def parse_indicate_payload(payload: bytes) -> NinjaState | None:
    """Parse a decrypted b004 indication payload.

    The exact binary layout is not yet documented. If the payload
    looks like JSON (starts with '{'), parse it as JSON. Otherwise
    log the raw bytes for future analysis.
    """
    if not payload:
        return None

    if payload[0:1] == b'{':
        return parse_grill_state_json(payload)

    # Binary payload — log for analysis, return None until layout is known
    _LOGGER.debug(
        "Binary indicate payload (%d bytes): %s",
        len(payload),
        payload.hex(" "),
    )
    return None


def apply_indicate(state: NinjaState, payload: bytes) -> NinjaState:
    """Return updated NinjaState from a new indicate payload."""
    parsed = parse_indicate_payload(payload)
    if parsed is None:
        # Keep existing state, just update raw payload
        return NinjaState(
            raw_indicate=payload,
            raw_notify=state.raw_notify,
            connected=state.connected,
            state=state.state,
            lid_open=state.lid_open,
            wood_fire=state.wood_fire,
            cook_mode=state.cook_mode,
            cook_type=state.cook_type,
            oven_current_temp_c=state.oven_current_temp_c,
            oven_desired_temp_c=state.oven_desired_temp_c,
            oven_time_set_s=state.oven_time_set_s,
            oven_time_left_s=state.oven_time_left_s,
            oven_on=state.oven_on,
            ignition_progress=state.ignition_progress,
            preheat_progress=state.preheat_progress,
            cook_progress=state.cook_progress,
            resting_progress=state.resting_progress,
            probe1=state.probe1,
            probe2=state.probe2,
            error=state.error,
            connected_to_internet=state.connected_to_internet,
        )

    parsed.raw_indicate = payload
    parsed.raw_notify = state.raw_notify
    parsed.connected = state.connected
    return parsed


def apply_notify(state: NinjaState, payload: bytes) -> NinjaState:
    """Return updated NinjaState from a new notify payload."""
    # b003 notify payloads not yet documented
    _LOGGER.debug("Notify payload (%d bytes): %s", len(payload), payload.hex(" "))
    new = NinjaState(
        raw_indicate=state.raw_indicate,
        raw_notify=payload,
        connected=state.connected,
    )
    # Copy all known fields
    for attr in ("state", "lid_open", "wood_fire", "cook_mode", "cook_type",
                 "oven_current_temp_c", "oven_desired_temp_c", "oven_time_set_s",
                 "oven_time_left_s", "oven_on", "ignition_progress",
                 "preheat_progress", "cook_progress", "resting_progress",
                 "probe1", "probe2", "error", "connected_to_internet"):
        setattr(new, attr, getattr(state, attr))
    return new
