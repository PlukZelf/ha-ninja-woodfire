"""Config flow for Ninja Woodfire integration.

Supports:
- Automatic discovery via HA Bluetooth integration (preferred).
- Manual entry of a Bluetooth address as fallback.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME

from .const import BLE_NAME_PREFIX, CONF_ADDRESS, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): str,
        vol.Optional(CONF_NAME, default="Ninja Woodfire"): str,
    }
)


class NinjaWoodfireConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Ninja Woodfire."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered via HA Bluetooth."""
        address = discovery_info.address
        name = discovery_info.name or f"Ninja Woodfire ({address})"

        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self._discovered_address = address
        self._discovered_name = name

        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a Bluetooth-discovered device."""
        if user_input is not None:
            return self._create_entry(
                address=self._discovered_address,  # type: ignore[arg-type]
                name=self._discovered_name or "Ninja Woodfire",
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovered_name,
                "address": self._discovered_address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            name = user_input.get(CONF_NAME, "Ninja Woodfire")

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self._create_entry(address=address, name=name)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    def _create_entry(self, address: str, name: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name,
            data={
                CONF_ADDRESS: address,
                CONF_NAME: name,
            },
        )
