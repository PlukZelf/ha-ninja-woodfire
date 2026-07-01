"""Number entities for Ninja Woodfire controls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from . import commands
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator
from .protocol import NinjaState


@dataclass(frozen=True, kw_only=True)
class NinjaNumberDescription(NumberEntityDescription):
    current_fn: Callable[[NinjaState], float | None]
    command_fn: Callable[[int], bytes]
    # When set, the entity is only available while the (effective) cook type
    # matches — cook time applies to Timed cooks, probe targets to Probe cooks.
    requires_cook_type: str | None = None


NUMBER_DESCRIPTIONS: tuple[NinjaNumberDescription, ...] = (
    NinjaNumberDescription(
        key="probe1_target_temperature",
        name="Probe 1 Target Temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=commands.MIN_TEMP_C,
        native_max_value=commands.MAX_TEMP_C,
        native_step=5,
        current_fn=lambda s: s.probe1.desired_temp_c or None,
        command_fn=commands.set_probe1_target_temp,
        requires_cook_type="Probe",
    ),
    NinjaNumberDescription(
        key="probe2_target_temperature",
        name="Probe 2 Target Temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=commands.MIN_TEMP_C,
        native_max_value=commands.MAX_TEMP_C,
        native_step=5,
        current_fn=lambda s: s.probe2.desired_temp_c or None,
        command_fn=commands.set_probe2_target_temp,
        requires_cook_type="Probe",
    ),
    NinjaNumberDescription(
        key="cook_time",
        name="Cook Time",
        icon="mdi:timer",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=commands.MIN_COOK_MINUTES,
        native_max_value=commands.MAX_COOK_MINUTES,
        native_step=1,
        current_fn=lambda s: s.oven_time_set_s // 60,
        command_fn=commands.set_cook_time,
        requires_cook_type="Timed",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities(
        NinjaWoodfireNumber(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    )


class NinjaWoodfireNumber(CoordinatorEntity[NinjaWoodfireCoordinator], NumberEntity):
    entity_description: NinjaNumberDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NinjaWoodfireCoordinator,
        description: NinjaNumberDescription,
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
        # STUB: locally remembered value, used only while
        # commands.OPTIMISTIC_CONTROLS is True. See commands.py.
        self._optimistic_value: float | None = None

    @property
    def available(self) -> bool:
        # STUB: while optimistic, ignore connection state so the UI is usable
        # offline; only the cook-type gating applies. Remove once decoding works.
        if not commands.OPTIMISTIC_CONTROLS and not super().available:
            return False
        required = self.entity_description.requires_cook_type
        if required is None:
            return True
        return self.coordinator.effective_cook_type == required

    @property
    def native_value(self) -> float | None:
        if commands.OPTIMISTIC_CONTROLS and self._optimistic_value is not None:
            return self._optimistic_value
        if self.coordinator.data is None:
            return None
        return self.entity_description.current_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        # TEMPORARY: nothing is transmitted yet (see commands.OPTIMISTIC_CONTROLS).
        # Remember the value locally so the UI reflects it, then attempt the
        # (currently no-op) command. Remove the optimistic block once decoding works.
        if commands.OPTIMISTIC_CONTROLS:
            self._optimistic_value = value
            self.async_write_ha_state()
        await self.coordinator.async_send_command(
            lambda: self.entity_description.command_fn(int(value))
        )
