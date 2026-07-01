"""Select entities for Ninja Woodfire controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from . import commands
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator
from .protocol import NinjaState


@dataclass(frozen=True, kw_only=True)
class NinjaSelectDescription(SelectEntityDescription):
    current_fn: Callable[[NinjaState], str | None]
    command_fn: Callable[[str], bytes]


SELECT_DESCRIPTIONS: tuple[NinjaSelectDescription, ...] = (
    NinjaSelectDescription(
        key="cook_function",
        name="Cook Function",
        icon="mdi:food",
        options=list(commands.COOK_MODES),
        current_fn=lambda s: s.cook_mode if s.cook_mode in commands.COOK_MODES else None,
        command_fn=commands.set_cook_mode,
    ),
    NinjaSelectDescription(
        key="cook_type",
        name="Cook Type",
        icon="mdi:thermometer",
        options=list(commands.COOK_TYPES),
        current_fn=lambda s: s.cook_type if s.cook_type in commands.COOK_TYPES else None,
        command_fn=commands.set_cook_type,
    ),
    NinjaSelectDescription(
        key="wood_flavor",
        name="Wood Flavor",
        icon="mdi:tree",
        options=list(commands.WOOD_FLAVORS),
        current_fn=lambda s: None,
        command_fn=commands.set_wood_flavor,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities(
        NinjaWoodfireSelect(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    )


class NinjaWoodfireSelect(CoordinatorEntity[NinjaWoodfireCoordinator], SelectEntity):
    entity_description: NinjaSelectDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NinjaWoodfireCoordinator,
        description: NinjaSelectDescription,
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
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.current_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_send_command(
            lambda: self.entity_description.command_fn(option)
        )
