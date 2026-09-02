"""Data update coordinator for Hue Ambilight."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_SIDES,
    DEFAULT_SIDES,
    ATTR_COLOR_HEX,
    ATTR_COLOR_R,
    ATTR_COLOR_G,
    ATTR_COLOR_B,
    ATTR_SIDES_COLORS,
    ATTR_TV_ONLINE,
)
from .philips_tv import (
    PhilipsTVClient,
    PhilipsTVOfflineError,
    PhilipsTVError,
    parse_ambilight_colors,
    average_colors,
)

_LOGGER = logging.getLogger(__name__)


class AmbilightCoordinator(DataUpdateCoordinator):
    """
    Manages polling the Philips TV Ambilight API and pushing colors to lights.

    Data structure returned by _async_update_data:
    {
        "online": bool,
        "r": int,
        "g": int,
        "b": int,
        "color_hex": "#RRGGBB",
        "sides_colors": {"left": (r,g,b), "right": (r,g,b), ...},
    }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: PhilipsTVClient,
        config_entry_id: str,
        scan_interval_ms: int,
        sides: list[str],
        target_lights: list[str],
        transition: int,
        brightness_factor: float,
    ) -> None:
        self.client = client
        self.config_entry_id = config_entry_id
        self.sides = sides
        self.target_lights = target_lights
        self.transition = transition
        self.brightness_factor = brightness_factor
        self.sync_enabled = False
        self._last_color: tuple[int, int, int] = (0, 0, 0)
        self._last_data: dict[str, Any] = {
            "online": False,
            "r": 0,
            "g": 0,
            "b": 0,
            "color_hex": "#000000",
            "sides_colors": {},
        }

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(milliseconds=scan_interval_ms),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest ambilight color from TV."""
        try:
            raw = await self.hass.async_add_executor_job(
                self.client.get_ambilight_processed
            )
        except PhilipsTVOfflineError:
            _LOGGER.debug("TV is offline, using last known color")
            return {**self._last_data, "online": False}
        except PhilipsTVError as err:
            _LOGGER.warning("Ambilight API error: %s", err)
            return {**self._last_data, "online": False}

        side_colors = parse_ambilight_colors(raw, self.sides)
        avg_r, avg_g, avg_b = average_colors(side_colors, self.sides)

        color_hex = f"#{avg_r:02x}{avg_g:02x}{avg_b:02x}"

        data: dict[str, Any] = {
            "online": True,
            "r": avg_r,
            "g": avg_g,
            "b": avg_b,
            "color_hex": color_hex,
            "sides_colors": {k: list(v) for k, v in side_colors.items()},
        }
        self._last_data = data
        self._last_color = (avg_r, avg_g, avg_b)

        # Push color to lamps if sync is enabled and color changed
        if self.sync_enabled and self.target_lights:
            await self._push_color_to_lights(avg_r, avg_g, avg_b)

        return data

    async def _push_color_to_lights(self, r: int, g: int, b: int) -> None:
        """Apply the ambilight color to all configured HA light entities."""
        if r == 0 and g == 0 and b == 0:
            return  # Skip black (TV may be in dark scene or off)

        # Apply brightness factor
        if self.brightness_factor != 1.0:
            r = min(255, int(r * self.brightness_factor))
            g = min(255, int(g * self.brightness_factor))
            b = min(255, int(b * self.brightness_factor))

        service_data = {
            "rgb_color": [r, g, b],
            "transition": self.transition,
        }

        for light_entity_id in self.target_lights:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    {
                        "entity_id": light_entity_id,
                        **service_data,
                    },
                    blocking=False,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Failed to update light %s: %s", light_entity_id, err)

    def enable_sync(self) -> None:
        """Enable color synchronization to lights."""
        self.sync_enabled = True
        _LOGGER.info("Ambilight sync enabled for lights: %s", self.target_lights)

    def disable_sync(self) -> None:
        """Disable color synchronization to lights."""
        self.sync_enabled = False
        _LOGGER.info("Ambilight sync disabled")

    def update_lights(self, lights: list[str]) -> None:
        """Update the list of target light entities."""
        self.target_lights = lights

    def update_sides(self, sides: list[str]) -> None:
        """Update which screen sides to use for averaging."""
        self.sides = sides

    def update_brightness_factor(self, factor: float) -> None:
        """Update the brightness multiplier."""
        self.brightness_factor = factor
