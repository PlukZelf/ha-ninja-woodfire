"""Config flow for Ninja Woodfire integration.

Supports:
- Automatic discovery via HA Bluetooth integration (preferred).
- Manual entry of a Bluetooth address as fallback.
- Options flow: add or remove devices after initial setup.

Security:
- Only devices with the Ninja service UUID and NCEU name pattern are shown.
- User must explicitly confirm the device before it is stored.
- No automatic pairing with unknown devices.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from .const import BLE_NAME_PREFIX, CONF_ADDRESS, DOMAIN, NINJA_SERVICE_UUID

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): str,
        vol.Optional(CONF_NAME, default="Ninja Woodfire"): str,
    }
)


def _is_ninja_device(info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the advertisement looks like a genuine Ninja Woodfire."""
    has_service = NINJA_SERVICE_UUID in (info.service_uuids or [])
    has_name = (info.name or "").startswith(BLE_NAME_PREFIX)
    return has_service and has_name


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
        if not _is_ninja_device(discovery_info):
            return self.async_abort(reason="not_ninja_device")

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
        """Ask the user to confirm this is their device."""
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
        """Manual address entry with optional scan."""
        errors: dict[str, str] = {}

        discovered: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass):
            if _is_ninja_device(info):
                label = f"{info.name} ({info.address})"
                discovered[info.address] = label

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            name = user_input.get(CONF_NAME, "Ninja Woodfire")

            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            return self._create_entry(address=address, name=name)

        if discovered:
            schema = vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(discovered),
                    vol.Optional(CONF_NAME, default="Ninja Woodfire"): str,
                }
            )
        else:
            schema = STEP_USER_SCHEMA

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):  # type: ignore[override]
        return NinjaWoodfireOptionsFlow(config_entry)


class NinjaWoodfireOptionsFlow(OptionsFlow):
    """Handle options: rename device or remove it.

    Device management after initial setup:
    - Rename: change the display name.
    - Remove: handled via HA's standard device removal UI.

    Adding a second device is done by running the integration setup again
    (Add Integration), which creates a new config entry.
    """

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show current device info and allow rename."""
        current_name = self._config_entry.data.get(CONF_NAME, "Ninja Woodfire")
        address = self._config_entry.data.get(CONF_ADDRESS, "")

        if user_input is not None:
            new_name = user_input.get(CONF_NAME, current_name).strip()
            return self.async_create_entry(
                title=new_name,
                data={CONF_NAME: new_name},
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=current_name): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "address": address,
                "name": current_name,
            },
        )
