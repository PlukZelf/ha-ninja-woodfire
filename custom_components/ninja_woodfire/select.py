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
        current_fn=lambda s: (
            s.cook_mode
            if s.cook_mode in commands.COOK_MODES
            else commands.DEFAULT_COOK_MODE
        ),
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
        # STUB: locally remembered selection, used only while
        # commands.OPTIMISTIC_CONTROLS is True. See commands.py.
        self._optimistic_option: str | None = None

    @property
    def available(self) -> bool:
        # STUB: while optimistic, stay usable even without a live connection so
        # the UI can be exercised. Remove once decoding works.
        if commands.OPTIMISTIC_CONTROLS:
            return True
        return super().available

    @property
    def current_option(self) -> str | None:
        if commands.OPTIMISTIC_CONTROLS and self._optimistic_option is not None:
            return self._optimistic_option
        if self.coordinator.data is None:
            return None
        return self.entity_description.current_fn(self.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        # TEMPORARY: nothing is transmitted yet (see commands.OPTIMISTIC_CONTROLS).
        # Remember the choice locally so the UI reflects it, then attempt the
        # (currently no-op) command. Remove the optimistic block once decoding works.
        if commands.OPTIMISTIC_CONTROLS:
            self._optimistic_option = option
            # Cook type drives the availability of the time/probe controls.
            if self.entity_description.key == "cook_type":
                self.coordinator.set_optimistic_cook_type(option)
            self.async_write_ha_state()
        await self.coordinator.async_send_command(
            lambda: self.entity_description.command_fn(option)
        )
