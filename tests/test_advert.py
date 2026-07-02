"""Tests for the passive advertisement decode pipeline."""

from __future__ import annotations

import pytest

from custom_components.ninja_woodfire.advert import build_state_from_halves
from custom_components.ninja_woodfire.advert_decode import decode as decode_fields
from custom_components.ninja_woodfire.crypto import decode_advert_half

# Verified oracle vectors copied from tools/advert_crypto_port.py __main__.
# (raw_encrypted_hex, expected_plaintext_hex)
VEC_20 = (
    "000102030405060708090a0b0c0d0e0f10111213",
    "f5e3cbd0c4d9c29617e1b0ff2c3a5d3a1d5bf7b1",
)
VEC_23 = (
    "000102030405060708090a0b0c0d0e0f10111213141516",
    "f5e3cbd0c2ff0f07cabf4e8b3b26fb7af697ffcec8affc",
)
VEC_ZERO_20 = (
    "0000000000000000000000000000000000000000",
    "63a5e1ff5983da560a1190ac1f6a4516a64f2829",
)
VEC_ZERO_23 = (
    "0000000000000000000000000000000000000000000000",
    "63a5e1ff5ed5e0f70050a2da3eb607313d554ed73ca732",
)


@pytest.mark.parametrize(
    "raw_hex,expected_hex",
    [VEC_20, VEC_23, VEC_ZERO_20, VEC_ZERO_23],
)
def test_decode_advert_half_matches_oracle(raw_hex: str, expected_hex: str) -> None:
    raw = bytes.fromhex(raw_hex)
    assert decode_advert_half(raw).hex() == expected_hex


def test_decode_advert_half_rejects_bad_length() -> None:
    with pytest.raises(ValueError):
        decode_advert_half(b"\x00" * 16)  # too short
    with pytest.raises(ValueError):
        decode_advert_half(b"\x00" * 32)  # too long


def test_build_state_from_halves_rejects_wrong_lengths() -> None:
    with pytest.raises(ValueError):
        build_state_from_halves(b"\x00" * 19, b"\x00" * 23)
    with pytest.raises(ValueError):
        build_state_from_halves(b"\x00" * 20, b"\x00" * 22)


def test_build_state_from_halves_populates_state() -> None:
    """Feed the two verified zero-vectors; assert the pipeline runs end to end
    and produces a NinjaState with the expected structure and raw buffers."""
    half1 = bytes.fromhex(VEC_ZERO_20[0])  # 20 bytes
    half2 = bytes.fromhex(VEC_ZERO_23[0])  # 23 bytes
    state = build_state_from_halves(half1, half2)

    # Combined decoded plaintext stored in raw_indicate, encrypted in raw_notify.
    assert len(state.raw_indicate) == 43
    assert state.raw_notify == half1 + half2

    # Field decode is deterministic; assert it matches the standalone decoder.
    expected = bytes.fromhex(VEC_ZERO_20[1]) + bytes.fromhex(VEC_ZERO_23[1])
    assert state.raw_indicate == expected
    fields = decode_fields(expected)
    assert state.oven_time_left_s == fields["header"][13]
    assert state.oven_current_temp_c == fields["header"][14]
    assert state.oven_desired_temp_c == fields["header"][19]
    assert state.probe1.current_temp_c == fields["header"][15]
    assert state.probe1.desired_temp_c == fields["probes"][0][7]
    assert state.cook_mode in (
        "NotSet", "Grill", "AirCrisp", "Roast", "Bake",
        "Broil", "Smoke", "Dehydrate", "MaxRoast", "SlowCook",
    )
