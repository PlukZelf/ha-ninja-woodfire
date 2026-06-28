"""Tests for the Ninja Woodfire protocol parser.

These tests use observed payloads from spec/gatt.md. As more of the protocol
is understood, extend these tests with assertions on parsed fields.
"""

from __future__ import annotations

import pytest

from custom_components.ninja_woodfire.protocol import (
    NinjaState,
    apply_indicate,
    apply_notify,
    parse_indicate,
    parse_notify,
)

# Observed payloads from spec/gatt.md
SAMPLE_INDICATE_1 = bytes.fromhex(
    "a5a03031 50c16927 8dc7a844 4ce03687"
    "4df5df2d 64f93bdb 304a37ed d4b835e6"
    "ebce489b b5c4da70 f67af858 7e216a39"
    "205b8245 4bc3681b 49281ab3 c78ac1c4".replace(" ", "")
)

SAMPLE_INDICATE_2 = bytes.fromhex(
    "648ede4f bc946159 e843586b 7b3d5855"
    "4af3a417 48c3915e 174b44be 1701b1dd"
    "04e1cff2 5453d170 83e61834 44922856"
    "9df327ae cf8d1a42 9fe14ecf bae06564".replace(" ", "")
)


def test_parse_indicate_length_ok() -> None:
    """parse_indicate should accept a 64-byte payload without raising."""
    result = parse_indicate(SAMPLE_INDICATE_1)
    assert isinstance(result, dict)


def test_parse_indicate_wrong_length_returns_empty() -> None:
    """parse_indicate should return {} for payloads that are not 64 bytes."""
    assert parse_indicate(b"\x00" * 32) == {}
    assert parse_indicate(b"") == {}


def test_parse_notify_empty_returns_empty() -> None:
    assert parse_notify(b"") == {}


def test_apply_indicate_preserves_existing_state() -> None:
    """apply_indicate should carry over state fields that are not yet parsed."""
    initial = NinjaState(connected=True, cooking_mode="grill")
    updated = apply_indicate(initial, SAMPLE_INDICATE_1)
    # cooking_mode unknown in payload → preserved from initial
    assert updated.cooking_mode == "grill"
    assert updated.raw_indicate == SAMPLE_INDICATE_1


def test_apply_indicate_second_sample() -> None:
    initial = NinjaState(connected=True)
    updated = apply_indicate(initial, SAMPLE_INDICATE_2)
    assert updated.raw_indicate == SAMPLE_INDICATE_2


def test_apply_notify_preserves_indicate_payload() -> None:
    """apply_notify should not overwrite the raw_indicate buffer."""
    initial = NinjaState(raw_indicate=SAMPLE_INDICATE_1, connected=True)
    updated = apply_notify(initial, b"\x01\x02")
    assert updated.raw_indicate == SAMPLE_INDICATE_1
    assert updated.raw_notify == b"\x01\x02"


def test_ninja_state_defaults() -> None:
    state = NinjaState()
    assert state.connected is False
    assert state.power_on is None
    assert state.cooking_mode is None
    assert state.target_temp_c is None
    assert state.probe_temp_c is None
    assert state.timer_remaining_s is None
    assert state.error_code is None
