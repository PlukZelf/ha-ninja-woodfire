"""Tests for the Ninja Woodfire protocol parser.

These tests use observed payloads from spec/gatt.md. As more of the protocol
is understood, extend these tests with assertions on parsed fields.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROTOCOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "ninja_woodfire"
    / "protocol.py"
)
_SPEC = importlib.util.spec_from_file_location("ninja_woodfire_protocol", _PROTOCOL_PATH)
assert _SPEC is not None
protocol = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = protocol
_SPEC.loader.exec_module(protocol)

NinjaState = protocol.NinjaState
apply_indicate = protocol.apply_indicate
apply_notify = protocol.apply_notify
parse_indicate_payload = protocol.parse_indicate_payload

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


def test_parse_indicate_encrypted_payload_returns_none() -> None:
    """Encrypted/raw payloads are preserved until their layout is known."""
    assert parse_indicate_payload(SAMPLE_INDICATE_1) is None


def test_parse_indicate_empty_returns_none() -> None:
    assert parse_indicate_payload(b"") is None


def test_parse_indicate_json_payload() -> None:
    state = parse_indicate_payload(
        b'{"state":"Cooking","cookMode":"Grill","oven":{"currentTemp":180}}'
    )
    assert state is not None
    assert state.state == "Cooking"
    assert state.cook_mode == "Grill"
    assert state.oven_current_temp_c == 180


def test_apply_indicate_preserves_existing_state() -> None:
    """apply_indicate should carry over state fields that are not yet parsed."""
    initial = NinjaState(connected=True, cook_mode="Grill")
    updated = apply_indicate(initial, SAMPLE_INDICATE_1)
    assert updated.cook_mode == "Grill"
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
    assert state.state == "Unknown"
    assert state.cook_mode == "NotSet"
    assert state.oven_current_temp_c == 0
    assert state.oven_desired_temp_c == 0
    assert state.oven_time_left_s == 0
    assert state.error == 0
