"""Switch entity — enable/disable Ambilight sync."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_TV_IP
from .coordinator import AmbilightCoordinator

_LOGGER = logging.getLogger(__name__)

SWITCH_DESCRIPTION = SwitchEntityDescription(
    key="ambilight_sync",
    translation_key="ambilight_sync",
    icon="mdi:television-ambient-light",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Ambilight sync switch."""
    coordinator: AmbilightCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AmbilightSyncSwitch(coordinator, entry)])


class AmbilightSyncSwitch(CoordinatorEntity[AmbilightCoordinator], SwitchEntity):
    """Switch to enable/disable real-time Ambilight → lights synchronization."""

    entity_description = SWITCH_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmbilightCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sync_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Philips TV Ambilight ({entry.data.get(CONF_TV_IP, 'unknown')})",
            manufacturer="Philips",
            model="Ambilight Sync",
        )

    @property
    def is_on(self) -> bool:
        """Return True if sync is active."""
        return self.coordinator.sync_enabled

    @property
    def available(self) -> bool:
        """Always available — sync can be toggled even if TV is temporarily offline."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        data = self.coordinator.data or {}
        return {
            "tv_online": data.get("tv_online", False),
            "tv_on": data.get("tv_on", False),
            "powerstate": data.get("powerstate", "Off"),
            "current_color": data.get("color_hex", "#000000"),
            "target_lights": self.coordinator.target_lights,
            "sides": self.coordinator.sides,
            "scan_interval_ms": self.coordinator.update_interval.total_seconds() * 1000,
            "brightness_factor": self.coordinator.brightness_factor,
            "color_threshold": self.coordinator.color_threshold,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Ambilight sync."""
        self.coordinator.enable_sync()
        # Force immediate coordinator refresh
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Ambilight sync."""
        self.coordinator.disable_sync()
        self.async_write_ha_state()
