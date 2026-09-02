"""Sensor entity — current Ambilight color."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_TV_IP, ATTR_SIDES_COLORS
from .coordinator import AmbilightCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTION = SensorEntityDescription(
    key="ambilight_color",
    name="Ambilight Color",
    icon="mdi:palette",
    native_unit_of_measurement=None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ambilight color sensor."""
    coordinator: AmbilightCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmbilightColorSensor(coordinator, entry)])


class AmbilightColorSensor(CoordinatorEntity[AmbilightCoordinator], SensorEntity):
    """Sensor showing the current averaged Ambilight color as a hex string."""

    entity_description = SENSOR_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmbilightCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_color_sensor"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Philips TV Ambilight ({entry.data.get(CONF_TV_IP, 'unknown')})",
            manufacturer="Philips",
            model="Ambilight Sync",
        )

    @property
    def native_value(self) -> str:
        """Return the current average color as #RRGGBB hex string."""
        data = self.coordinator.data or {}
        return data.get("color_hex", "#000000")

    @property
    def available(self) -> bool:
        """Return True if TV was online in the last update."""
        data = self.coordinator.data or {}
        return data.get("online", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed color data as attributes."""
        data = self.coordinator.data or {}
        return {
            "r": data.get("r", 0),
            "g": data.get("g", 0),
            "b": data.get("b", 0),
            "sides_colors": data.get("sides_colors", {}),
            "tv_online": data.get("online", False),
        }
