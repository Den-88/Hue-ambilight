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
    CONF_LIGHTS_LEFT_BOTTOM,
    CONF_LIGHTS_RIGHT_BOTTOM,
    CONF_LIGHTS_LEFT,
    CONF_LIGHTS_RIGHT,
    CONF_LIGHTS_TOP,
    CONF_LIGHTS_BOTTOM,
    CONF_LIGHTS_ALL,
    CONF_SCAN_INTERVAL,
    CONF_SIDES,
    CONF_TRANSITION,
    CONF_BRIGHTNESS_FACTOR,
    CONF_COLOR_THRESHOLD,
    CONF_SYNC_ENABLED,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SIDES,
    DEFAULT_TRANSITION,
    DEFAULT_BRIGHTNESS_FACTOR,
    DEFAULT_COLOR_THRESHOLD,
    DEFAULT_SYNC_ENABLED,
)
from .philips_tv import PhilipsTVClient, PhilipsTVOfflineError
from .coordinator import AmbilightCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hue Ambilight from a config entry."""
    # Options override initial config_entry data
    cfg = {**entry.data, **entry.options}

    client = PhilipsTVClient(
        host=cfg[CONF_TV_IP],
        port=cfg.get(CONF_TV_PORT, DEFAULT_PORT),
        username=cfg.get(CONF_USERNAME),
        password=cfg.get(CONF_PASSWORD),
    )

    # Verify TV is reachable (non-fatal — TV may be off at startup)
    online = await hass.async_add_executor_job(client.is_online)
    if not online:
        _LOGGER.warning(
            "Philips TV at %s is not reachable. Will retry automatically.",
            cfg[CONF_TV_IP],
        )

    all_lights = cfg.get(CONF_LIGHTS_ALL, cfg.get(CONF_LIGHTS, []))

    # Preserve sync_enabled state across reloads and HA restarts
    existing_coord: AmbilightCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    initial_sync = (
        existing_coord.sync_enabled
        if existing_coord is not None
        else cfg.get(CONF_SYNC_ENABLED, DEFAULT_SYNC_ENABLED)
    )

    coordinator = AmbilightCoordinator(
        hass=hass,
        client=client,
        config_entry_id=entry.entry_id,
        scan_interval_ms=cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        sides=cfg.get(CONF_SIDES, DEFAULT_SIDES),
        target_lights=all_lights,
        transition=cfg.get(CONF_TRANSITION, DEFAULT_TRANSITION),
        brightness_factor=cfg.get(CONF_BRIGHTNESS_FACTOR, DEFAULT_BRIGHTNESS_FACTOR),
        color_threshold=cfg.get(CONF_COLOR_THRESHOLD, DEFAULT_COLOR_THRESHOLD),
        sync_enabled=initial_sync,
        lights_left=cfg.get(CONF_LIGHTS_LEFT, []),
        lights_right=cfg.get(CONF_LIGHTS_RIGHT, []),
        lights_top=cfg.get(CONF_LIGHTS_TOP, []),
        lights_bottom=cfg.get(CONF_LIGHTS_BOTTOM, []),
        lights_all=all_lights,
        lights_left_bottom=cfg.get(CONF_LIGHTS_LEFT_BOTTOM, []),
        lights_right_bottom=cfg.get(CONF_LIGHTS_RIGHT_BOTTOM, []),
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
    """Handle options update — update coordinator dynamically in-place without reloading."""
    coordinator: AmbilightCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not coordinator:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    cfg = {**entry.data, **entry.options}
    all_lights = cfg.get(CONF_LIGHTS_ALL, cfg.get(CONF_LIGHTS, []))

    coordinator.update_zone_lights(
        lights_left_bottom=cfg.get(CONF_LIGHTS_LEFT_BOTTOM, []),
        lights_right_bottom=cfg.get(CONF_LIGHTS_RIGHT_BOTTOM, []),
        lights_left=cfg.get(CONF_LIGHTS_LEFT, []),
        lights_right=cfg.get(CONF_LIGHTS_RIGHT, []),
        lights_top=cfg.get(CONF_LIGHTS_TOP, []),
        lights_bottom=cfg.get(CONF_LIGHTS_BOTTOM, []),
        lights_all=all_lights,
    )
    coordinator.update_sides(cfg.get(CONF_SIDES, DEFAULT_SIDES))
    coordinator.update_transition(cfg.get(CONF_TRANSITION, DEFAULT_TRANSITION))
    coordinator.update_brightness_factor(cfg.get(CONF_BRIGHTNESS_FACTOR, DEFAULT_BRIGHTNESS_FACTOR))
    coordinator.update_color_threshold(cfg.get(CONF_COLOR_THRESHOLD, DEFAULT_COLOR_THRESHOLD))
    coordinator.update_scan_interval(cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    if CONF_SYNC_ENABLED in cfg:
        if cfg[CONF_SYNC_ENABLED]:
            coordinator.enable_sync()
        else:
            coordinator.disable_sync()

