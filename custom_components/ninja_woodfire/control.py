"""GATT command/control path for the Ninja Woodfire integration.

This is the WRITE side (setting target temperature, later cook mode / timer).
It is deliberately separated from the passive read-only coordinator so the
monitoring path is never affected by control code.

Status: the local BLE GATT command channel is AES-encrypted with a per-session
key (established by a Connect handshake). That crypto is not yet reversed, so
``async_set_target_temperature`` cannot actually reach the grill yet — it raises
``ControlNotReady`` with a clear message. The control *entities* exist and are
wired so that the moment the crypto lands (a pure-Python ``gatt_crypto`` module),
only this file needs to gain the real connect->handshake->encrypt->write flow.

See ``docs/send-commands-plan.md`` (Phases 2-6) and
``docs/gatt-crypto-solved.md`` for the crypto status.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


class ControlNotReady(HomeAssistantError):
    """Raised when a control command is attempted before the GATT crypto lands.

    Surfaces in the HA UI as a clear error instead of a silent no-op or a
    traceback, so it is obvious that control is not yet available.
    """


# Plausible target-temperature bounds for the Woodfire Pro (celsius). These are
# UI guardrails for the number entity, not protocol-derived limits.
TEMP_MIN_C = 40
TEMP_MAX_C = 260
TEMP_STEP_C = 5


class NinjaWoodfireControl:
    """Owns the (future) GATT command connection to the grill.

    Today every command raises ``ControlNotReady``. The method signatures and
    the connect->handshake->send->disconnect model match
    ``tools/gatt_send/ninja_client.py`` so wiring the real crypto is a drop-in.
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self._hass = hass
        self._address = address

    @property
    def available(self) -> bool:
        """Whether local BLE control is functional.

        False until the per-session GATT crypto is reversed and a pure-Python
        ``gatt_crypto`` module is vendored into the integration.
        """
        return False

    async def async_set_target_temperature(self, celsius: int) -> None:
        """Set the grill's target temperature over local BLE.

        Once the crypto lands this performs: connect -> enable indications ->
        receive 20B challenge -> derive_key -> auth write -> encrypt SetTemp ->
        write b002 -> disconnect (the transient-connection model). Until then it
        raises ``ControlNotReady``.
        """
        _LOGGER.debug(
            "SetTemp(%s) requested for %s but GATT command crypto is not yet "
            "implemented; command not sent",
            celsius,
            self._address,
        )
        raise ControlNotReady(
            "Sending commands to the grill over local BLE is not available yet: "
            "the GATT command encryption (per-session key) is still being "
            "reverse-engineered. Reading state works; setting values does not "
            "yet. See docs/send-commands-plan.md."
        )
