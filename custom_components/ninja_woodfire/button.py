"""Button entities for Ninja Woodfire actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from . import commands
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator


@dataclass(frozen=True, kw_only=True)
class NinjaButtonDescription(ButtonEntityDescription):
    command_fn: Callable[[], bytes]


BUTTON_DESCRIPTIONS: tuple[NinjaButtonDescription, ...] = (
    NinjaButtonDescription(
        key="start_cook",
        name="Start Cook",
        icon="mdi:play",
        command_fn=commands.start_cook,
    ),
    NinjaButtonDescription(
        key="stop_cook",
        name="Stop Cook",
        icon="mdi:stop",
        command_fn=commands.stop_cook,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities(
        NinjaWoodfireButton(coordinator, description)
        for description in BUTTON_DESCRIPTIONS
    )


class NinjaWoodfireButton(CoordinatorEntity[NinjaWoodfireCoordinator], ButtonEntity):
    entity_description: NinjaButtonDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NinjaWoodfireCoordinator,
        description: NinjaButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": coordinator.device_name,
            "manufacturer": "Ninja",
            "model": "Woodfire Pro",
        }

    @property
    def available(self) -> bool:
        # STUB: while optimistic, stay usable even without a live connection so
        # the UI can be exercised. Remove once decoding works.
        if commands.OPTIMISTIC_CONTROLS:
            return True
        return super().available

    async def async_press(self) -> None:
        await self.coordinator.async_send_command(self.entity_description.command_fn)
