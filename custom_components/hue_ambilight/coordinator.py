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
    CONF_LIGHTS,
    CONF_LIGHTS_LEFT,
    CONF_LIGHTS_RIGHT,
    CONF_LIGHTS_TOP,
    CONF_LIGHTS_BOTTOM,
    CONF_LIGHTS_ALL,
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
    parse_ambilight_pixels,
    average_colors,
)

_LOGGER = logging.getLogger(__name__)


class AmbilightCoordinator(DataUpdateCoordinator):
    """
    Manages polling the Philips TV Ambilight API and pushing colors to lights.
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
        lights_left: list[str] | None = None,
        lights_right: list[str] | None = None,
        lights_top: list[str] | None = None,
        lights_bottom: list[str] | None = None,
        lights_all: list[str] | None = None,
    ) -> None:
        self.client = client
        self.config_entry_id = config_entry_id
        self.sides = sides
        self.target_lights = target_lights
        self.transition = transition
        self.brightness_factor = brightness_factor
        self.lights_left = lights_left or []
        self.lights_right = lights_right or []
        self.lights_top = lights_top or []
        self.lights_bottom = lights_bottom or []
        self.lights_all = lights_all or target_lights or []
        self.sync_enabled = False
        self._last_color: tuple[int, int, int] = (0, 0, 0)
        self._last_data: dict[str, Any] = {
            "online": False,
            "r": 0,
            "g": 0,
            "b": 0,
            "color_hex": "#000000",
            "sides_colors": {},
            "pixels": {},
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
                self.client.get_ambilight_colors
            )
        except PhilipsTVOfflineError:
            _LOGGER.debug("TV is offline, using last known color")
            return {**self._last_data, "online": False}
        except PhilipsTVError as err:
            _LOGGER.warning("Ambilight API error: %s", err)
            return {**self._last_data, "online": False}

        side_colors = parse_ambilight_colors(raw, self.sides)
        pixels_data = parse_ambilight_pixels(raw)
        avg_r, avg_g, avg_b = average_colors(side_colors, self.sides)

        color_hex = f"#{avg_r:02x}{avg_g:02x}{avg_b:02x}"

        data: dict[str, Any] = {
            "online": True,
            "r": avg_r,
            "g": avg_g,
            "b": avg_b,
            "color_hex": color_hex,
            "sides_colors": {k: list(v) for k, v in side_colors.items()},
            "pixels": pixels_data,
        }
        self._last_data = data
        self._last_color = (avg_r, avg_g, avg_b)

        # Push colors per zone if sync is enabled
        if self.sync_enabled:
            await self._push_zone_colors(side_colors, (avg_r, avg_g, avg_b))

        return data

    async def _push_zone_colors(
        self,
        side_colors: dict[str, tuple[int, int, int]],
        avg_color: tuple[int, int, int],
    ) -> None:
        """Push corresponding side colors to configured zone light entities."""
        # 1. Left zone
        if self.lights_left and "left" in side_colors:
            lr, lg, lb = side_colors["left"]
            await self._push_color_to_lights(self.lights_left, lr, lg, lb)

        # 2. Right zone
        if self.lights_right and "right" in side_colors:
            rr, rg, rb = side_colors["right"]
            await self._push_color_to_lights(self.lights_right, rr, rg, rb)

        # 3. Top zone
        if self.lights_top and "top" in side_colors:
            tr, tg, tb = side_colors["top"]
            await self._push_color_to_lights(self.lights_top, tr, tg, tb)

        # 4. Bottom zone
        if self.lights_bottom and "bottom" in side_colors:
            br, bg, bb = side_colors["bottom"]
            await self._push_color_to_lights(self.lights_bottom, br, bg, bb)

        # 5. All zone (or legacy target_lights)
        all_target = self.lights_all or self.target_lights
        if all_target:
            # If specific zone lights were pushed, avoid re-pushing to them if they are in all_target
            ar, ag, ab = avg_color
            await self._push_color_to_lights(all_target, ar, ag, ab)

    async def _push_color_to_lights(
        self, lights: list[str], r: int, g: int, b: int
    ) -> None:
        """Apply RGB color to specified light entities."""
        if not lights or (r == 0 and g == 0 and b == 0):
            return

        # Apply brightness factor
        if self.brightness_factor != 1.0:
            r = min(255, int(r * self.brightness_factor))
            g = min(255, int(g * self.brightness_factor))
            b = min(255, int(b * self.brightness_factor))

        service_data = {
            "rgb_color": [r, g, b],
            "transition": self.transition,
        }

        for light_entity_id in lights:
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
        _LOGGER.info("Ambilight sync enabled")

    def disable_sync(self) -> None:
        """Disable color synchronization to lights."""
        self.sync_enabled = False
        _LOGGER.info("Ambilight sync disabled")

    def update_zone_lights(
        self,
        lights_left: list[str],
        lights_right: list[str],
        lights_top: list[str],
        lights_bottom: list[str],
        lights_all: list[str],
    ) -> None:
        """Update zone light entity mappings."""
        self.lights_left = lights_left
        self.lights_right = lights_right
        self.lights_top = lights_top
        self.lights_bottom = lights_bottom
        self.lights_all = lights_all
        self.target_lights = lights_all

    def update_sides(self, sides: list[str]) -> None:
        """Update which screen sides to use for averaging."""
        self.sides = sides

    def update_brightness_factor(self, factor: float) -> None:
        """Update the brightness multiplier."""
        self.brightness_factor = factor

    def update_scan_interval(self, interval_ms: int) -> None:
        """Update scan interval dynamically in milliseconds."""
        self.update_interval = timedelta(milliseconds=interval_ms)

    def update_transition(self, transition: int) -> None:
        """Update transition time in seconds."""
        self.transition = transition
