"""Number entities for Ninja Woodfire (control path).

Currently one entity: the target (desired) oven temperature. It READS the live
value from the passive advertisement coordinator, and SETTING it delegates to
``NinjaWoodfireControl`` (the local-BLE GATT command path). Because the GATT
command crypto is not yet reversed, a set attempt raises ``ControlNotReady``,
which HA surfaces as a clear error. The entity exists now so the control surface
is complete the moment the crypto lands — only ``control.py`` needs the real
encrypt/write flow then.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NinjaWoodfireConfigEntry
from .const import DOMAIN
from .control import NinjaWoodfireControl, TEMP_MAX_C, TEMP_MIN_C, TEMP_STEP_C
from .coordinator import NinjaWoodfireCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinjaWoodfireConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NinjaWoodfireCoordinator = entry.runtime_data
    control = NinjaWoodfireControl(hass, coordinator.address)
    async_add_entities([NinjaTargetTemperature(coordinator, control)])


class NinjaTargetTemperature(
    CoordinatorEntity[NinjaWoodfireCoordinator], NumberEntity
):
    """Target oven temperature: reads live state, writes via local-BLE control."""

    _attr_has_entity_name = True
    _attr_name = "Target Temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = TEMP_MIN_C
    _attr_native_max_value = TEMP_MAX_C
    _attr_native_step = TEMP_STEP_C
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer"

    def __init__(
        self,
        coordinator: NinjaWoodfireCoordinator,
        control: NinjaWoodfireControl,
    ) -> None:
        super().__init__(coordinator)
        self._control = control
        self._attr_unique_id = f"{coordinator.address}_set_target_temp"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": coordinator.device_name,
            "manufacturer": "Ninja",
            "model": "Woodfire Pro",
        }

    @property
    def native_value(self) -> float | None:
        """The grill's current target temperature, read from advertisements."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.oven_desired_temp_c or None

    async def async_set_native_value(self, value: float) -> None:
        """Send a new target temperature to the grill over local BLE.

        Delegates to the control path. Raises ``ControlNotReady`` (surfaced by
        HA as an error) until the GATT command crypto is implemented.
        """
        await self._control.async_set_target_temperature(int(value))
