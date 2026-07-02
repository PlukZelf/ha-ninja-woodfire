"""Turn decrypted Ninja Woodfire advertisement halves into NinjaState."""

from __future__ import annotations

import logging

from .advert_decode import decode as decode_fields
from .crypto import decode_advert_half
from .protocol import NinjaState, ProbeState

_LOGGER = logging.getLogger(__name__)

# Cook mode enum order confirmed in docs/crypto-status.md (header field 3).
# NOTE: this order differs from protocol.COOK_MODES; use THIS table for adverts.
COOK_MODE_BY_INDEX = {
    0: "NotSet",
    1: "Grill",
    2: "AirCrisp",
    3: "Roast",
    4: "Bake",
    5: "Broil",
    6: "Smoke",
    7: "Dehydrate",
    8: "MaxRoast",
    9: "SlowCook",
}

# Expected encrypted half lengths.
HALF1_LEN = 20
HALF2_LEN = 23
COMBINED_LEN = 43


def build_state_from_halves(half1: bytes, half2: bytes) -> NinjaState:
    """Decrypt + decode the two advert halves into a populated NinjaState.

    Args:
        half1: the 20-byte encrypted manufacturer-data payload.
        half2: the 23-byte encrypted manufacturer-data payload.

    Returns:
        A populated NinjaState.

    Raises:
        ValueError: if either half is the wrong length or decoding fails.
    """
    if len(half1) != HALF1_LEN or len(half2) != HALF2_LEN:
        raise ValueError(
            f"unexpected advert half lengths: {len(half1)}, {len(half2)} "
            f"(expected {HALF1_LEN}, {HALF2_LEN})"
        )

    combined = decode_advert_half(half1) + decode_advert_half(half2)
    if len(combined) != COMBINED_LEN:
        raise ValueError(f"decoded advert length {len(combined)} != {COMBINED_LEN}")

    fields = decode_fields(combined)
    header = fields["header"]
    probes = fields["probes"]

    state = NinjaState()

    # Raw buffers for diagnostics.
    state.raw_indicate = combined            # decoded plaintext
    state.raw_notify = bytes(half1) + bytes(half2)  # raw encrypted halves

    # Cook mode (header[3]).
    state.cook_mode = COOK_MODE_BY_INDEX.get(header[3], "NotSet")

    # Oven / timer / temps.
    state.oven_time_left_s = header[13]
    state.oven_current_temp_c = header[14]
    state.oven_time_set_s = header[18]
    state.oven_desired_temp_c = header[19]

    # Probe 1: live temp is in the header (header[15]); target/plug flags in block.
    p1 = ProbeState(
        plugged_in=bool(probes[0][1]),
        active=bool(probes[0][2]),
        desired_temp_c=probes[0][7],
        current_temp_c=header[15],
    )
    # Probe 2: no confirmed live-temp source; plug/target flags from its block.
    p2 = ProbeState(
        plugged_in=bool(probes[1][1]),
        active=bool(probes[1][2]),
        desired_temp_c=probes[1][7],
        current_temp_c=0,
    )
    state.probe1 = p1
    state.probe2 = p2

    # Legacy mirror fields (kept consistent for diagnostics/tests).
    state.cooking_mode = state.cook_mode
    state.target_temp_c = state.oven_desired_temp_c
    state.timer_remaining_s = state.oven_time_left_s

    if p1.plugged_in:
        state.probe_temp_c = p1.current_temp_c
    elif p2.plugged_in:
        state.probe_temp_c = p2.current_temp_c
    else:
        state.probe_temp_c = None

    _LOGGER.debug(
        "Decoded advert: mode=%s oven=%s/%s°C time=%s/%ss p1=%s p2=%s "
        "(unmapped header=%s extra=%s final=%s)",
        state.cook_mode,
        state.oven_current_temp_c,
        state.oven_desired_temp_c,
        state.oven_time_left_s,
        state.oven_time_set_s,
        p1,
        p2,
        header,
        fields["extra_byte"],
        fields["final"],
    )

    return state
