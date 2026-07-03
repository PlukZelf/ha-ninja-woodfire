"""Sensor entities for Ninja Woodfire."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator
from .protocol import NinjaState


@dataclass(frozen=True, kw_only=True)
class NinjaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[NinjaState], float | int | str | None]


SENSOR_DESCRIPTIONS: tuple[NinjaSensorDescription, ...] = (
    # State
    NinjaSensorDescription(
        key="state",
        name="State",
        value_fn=lambda s: s.state,
        icon="mdi:grill",
    ),
    NinjaSensorDescription(
        key="cook_mode",
        name="Cook Mode",
        value_fn=lambda s: s.cook_mode,
        icon="mdi:food",
    ),
    # Oven temperatures
    NinjaSensorDescription(
        key="oven_current_temp",
        name="Grill Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.oven_current_temp_c or None,
    ),
    NinjaSensorDescription(
        key="oven_target_temp",
        name="Target Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.oven_desired_temp_c or None,
    ),
    # Timer
    NinjaSensorDescription(
        key="time_left",
        name="Time Remaining",
        # Bare duration-in-seconds (no state_class/precision) so the
        # frontend renders H:MM:SS instead of a raw number.
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda s: s.oven_time_left_s or None,
    ),
    NinjaSensorDescription(
        key="time_set",
        name="Cook Duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda s: s.oven_time_set_s or None,
    ),
    # Progress
    NinjaSensorDescription(
        key="cook_progress",
        name="Cook Progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.cook_progress or None,
        icon="mdi:progress-clock",
    ),
    NinjaSensorDescription(
        key="preheat_progress",
        name="Preheat Progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.preheat_progress or None,
        icon="mdi:thermometer-chevron-up",
    ),
    # Probe 1
    NinjaSensorDescription(
        key="probe1_temp",
        name="Probe 1 Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.probe1.current_temp_c if s.probe1.plugged_in else None,
    ),
    NinjaSensorDescription(
        key="probe1_target",
        name="Probe 1 Target",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.probe1.desired_temp_c if s.probe1.active else None,
    ),
    # Probe 2
    NinjaSensorDescription(
        key="probe2_temp",
        name="Probe 2 Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.probe2.current_temp_c if s.probe2.plugged_in else None,
    ),
    NinjaSensorDescription(
        key="probe2_target",
        name="Probe 2 Target",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.probe2.desired_temp_c if s.probe2.active else None,
    ),
    # Error code
    NinjaSensorDescription(
        key="error_code",
        name="Error Code",
        value_fn=lambda s: s.error if s.error else None,
        icon="mdi:alert-circle",
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities(
        NinjaWoodfireSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class NinjaWoodfireSensor(CoordinatorEntity[NinjaWoodfireCoordinator], SensorEntity):
    entity_description: NinjaSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NinjaWoodfireCoordinator,
        description: NinjaSensorDescription,
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
    def native_value(self) -> float | int | str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
