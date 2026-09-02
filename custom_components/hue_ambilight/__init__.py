"""Hue Ambilight integration — entry point."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_TV_IP,
    CONF_TV_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_LIGHTS,
    CONF_SCAN_INTERVAL,
    CONF_SIDES,
    CONF_TRANSITION,
    CONF_BRIGHTNESS_FACTOR,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SIDES,
    DEFAULT_TRANSITION,
    DEFAULT_BRIGHTNESS_FACTOR,
)
from .philips_tv import PhilipsTVClient, PhilipsTVOfflineError
from .coordinator import AmbilightCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hue Ambilight from a config entry."""
    data = entry.data

    client = PhilipsTVClient(
        host=data[CONF_TV_IP],
        port=data.get(CONF_TV_PORT, DEFAULT_PORT),
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
    )

    # Verify TV is reachable (non-fatal — TV may be off at startup)
    online = await hass.async_add_executor_job(client.is_online)
    if not online:
        _LOGGER.warning(
            "Philips TV at %s is not reachable. Will retry automatically.",
            data[CONF_TV_IP],
        )

    coordinator = AmbilightCoordinator(
        hass=hass,
        client=client,
        config_entry_id=entry.entry_id,
        scan_interval_ms=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        sides=data.get(CONF_SIDES, DEFAULT_SIDES),
        target_lights=data.get(CONF_LIGHTS, []),
        transition=data.get(CONF_TRANSITION, DEFAULT_TRANSITION),
        brightness_factor=data.get(CONF_BRIGHTNESS_FACTOR, DEFAULT_BRIGHTNESS_FACTOR),
    )

    # Initial data fetch (failure is OK — TV may be off)
    await coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: AmbilightCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        coordinator.disable_sync()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
