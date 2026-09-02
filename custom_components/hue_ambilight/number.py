"""Number platform for Hue Ambilight — sliders for live settings."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_TV_IP,
    CONF_SCAN_INTERVAL,
    CONF_TRANSITION,
    CONF_BRIGHTNESS_FACTOR,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRANSITION,
    DEFAULT_BRIGHTNESS_FACTOR,
    MIN_SCAN_INTERVAL_MS,
    MAX_SCAN_INTERVAL_MS,
)
from .coordinator import AmbilightCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator: AmbilightCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AmbilightScanIntervalNumber(coordinator, entry),
            AmbilightTransitionNumber(coordinator, entry),
            AmbilightBrightnessFactorNumber(coordinator, entry),
        ]
    )


class AmbilightBaseNumber(CoordinatorEntity[AmbilightCoordinator], NumberEntity):
    """Base class for Ambilight number settings."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AmbilightCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Philips TV Ambilight ({entry.data.get(CONF_TV_IP, 'unknown')})",
            manufacturer="Philips",
            model="Ambilight Sync",
        )

    async def _async_save_option(self, key: str, value: Any) -> None:
        """Helper to save updated value into ConfigEntry options."""
        current_options = dict(self._entry.options)
        current_options[key] = value
        self.hass.config_entries.async_update_entry(self._entry, options=current_options)


class AmbilightScanIntervalNumber(AmbilightBaseNumber):
    """Number entity for scan interval (ms)."""

    entity_description = NumberEntityDescription(
        key="scan_interval",
        name="Scan Interval (ms)",
        icon="mdi:timer-refresh-outline",
        native_min_value=MIN_SCAN_INTERVAL_MS,
        native_max_value=MAX_SCAN_INTERVAL_MS,
        native_step=50,
        native_unit_of_measurement="ms",
        mode=NumberMode.BOX,
    )

    def __init__(self, coordinator: AmbilightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_scan_interval"

    @property
    def native_value(self) -> float:
        """Return the current scan interval in milliseconds."""
        cfg = {**self._entry.data, **self._entry.options}
        return float(cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    async def async_set_native_value(self, value: float) -> None:
        """Update scan interval value."""
        val_int = int(value)
        self.coordinator.update_scan_interval(val_int)
        await self._async_save_option(CONF_SCAN_INTERVAL, val_int)


class AmbilightTransitionNumber(AmbilightBaseNumber):
    """Number entity for transition time (sec)."""

    entity_description = NumberEntityDescription(
        key="transition",
        name="Transition (sec)",
        icon="mdi:transition",
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.1,
        native_unit_of_measurement="s",
        mode=NumberMode.SLIDER,
    )

    def __init__(self, coordinator: AmbilightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_transition"

    @property
    def native_value(self) -> float:
        """Return current transition in seconds."""
        cfg = {**self._entry.data, **self._entry.options}
        return round(float(cfg.get(CONF_TRANSITION, DEFAULT_TRANSITION)), 1)

    async def async_set_native_value(self, value: float) -> None:
        """Update transition time in tenths of a second."""
        val_float = round(float(value), 1)
        self.coordinator.update_transition(val_float)
        await self._async_save_option(CONF_TRANSITION, val_float)


class AmbilightBrightnessFactorNumber(AmbilightBaseNumber):
    """Number entity for brightness factor multiplier."""

    entity_description = NumberEntityDescription(
        key="brightness_factor",
        name="Brightness Factor",
        icon="mdi:brightness-6",
        native_min_value=0.1,
        native_max_value=2.0,
        native_step=0.1,
        native_unit_of_measurement="x",
        mode=NumberMode.SLIDER,
    )

    def __init__(self, coordinator: AmbilightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_brightness_factor"

    @property
    def native_value(self) -> float:
        """Return current brightness factor."""
        cfg = {**self._entry.data, **self._entry.options}
        return round(float(cfg.get(CONF_BRIGHTNESS_FACTOR, DEFAULT_BRIGHTNESS_FACTOR)), 2)

    async def async_set_native_value(self, value: float) -> None:
        """Update brightness factor multiplier."""
        val_float = round(float(value), 2)
        self.coordinator.update_brightness_factor(val_float)
        await self._async_save_option(CONF_BRIGHTNESS_FACTOR, val_float)
