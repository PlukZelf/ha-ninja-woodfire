"""Binary sensor entities for Ninja Woodfire."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from .const import DOMAIN
from .coordinator import NinjaWoodfireCoordinator
from .protocol import NinjaState


@dataclass(frozen=True, kw_only=True)
class NinjaBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[NinjaState], bool | None]


BINARY_SENSOR_DESCRIPTIONS: tuple[NinjaBinarySensorDescription, ...] = (
    NinjaBinarySensorDescription(
        key="connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda s: s.connected,
    ),
    NinjaBinarySensorDescription(
        key="lid_open",
        name="Lid",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda s: s.lid_open,
    ),
    NinjaBinarySensorDescription(
        key="wood_fire",
        name="Woodfire Active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda s: s.wood_fire,
        icon="mdi:fire",
    ),
    NinjaBinarySensorDescription(
        key="probe1_plugged",
        name="Probe 1 Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda s: s.probe1.plugged_in,
    ),
    NinjaBinarySensorDescription(
        key="probe2_plugged",
        name="Probe 2 Connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda s: s.probe2.plugged_in,
    ),
    NinjaBinarySensorDescription(
        key="cooking",
        name="Cooking",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda s: s.state == "Cooking",
        icon="mdi:grill",
    ),
    NinjaBinarySensorDescription(
        key="preheating",
        name="Preheating",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda s: s.state == "Preheating",
        icon="mdi:thermometer-chevron-up",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    async_add_entities(
        NinjaWoodfireBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class NinjaWoodfireBinarySensor(CoordinatorEntity[NinjaWoodfireCoordinator], BinarySensorEntity):
    entity_description: NinjaBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NinjaWoodfireCoordinator,
        description: NinjaBinarySensorDescription,
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
        # The connectivity sensor must always be readable so it can report
        # "disconnected" — otherwise it would show "unavailable" the moment
        # the link drops, hiding the very state it exists to convey.
        if self.entity_description.key == "connected":
            return True
        return super().available

    @property
    def is_on(self) -> bool | None:
        if self.entity_description.key == "connected":
            return self.coordinator.is_connection_live
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
