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
    DEFAULT_COLOR_THRESHOLD,
    DEFAULT_STANDBY_SCAN_INTERVAL,
    ATTR_COLOR_HEX,
    ATTR_COLOR_R,
    ATTR_COLOR_G,
    ATTR_COLOR_B,
    ATTR_SIDES_COLORS,
    ATTR_TV_ONLINE,
    ATTR_TV_ON,
)
from .philips_tv import (
    PhilipsTVClient,
    PhilipsTVOfflineError,
    PhilipsTVError,
    parse_ambilight_colors,
    parse_ambilight_pixels,
    extract_corner_diodes,
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
        transition: float,
        brightness_factor: float,
        color_threshold: int = DEFAULT_COLOR_THRESHOLD,
        lights_left: list[str] | None = None,
        lights_right: list[str] | None = None,
        lights_top: list[str] | None = None,
        lights_bottom: list[str] | None = None,
        lights_all: list[str] | None = None,
        lights_left_bottom: list[str] | None = None,
        lights_right_bottom: list[str] | None = None,
    ) -> None:
        self.client = client
        self.config_entry_id = config_entry_id
        self.sides = sides
        self.target_lights = target_lights
        self.transition = transition
        self.brightness_factor = brightness_factor
        self.color_threshold = color_threshold
        self._scan_interval_ms = scan_interval_ms
        self._standby_interval_ms = DEFAULT_STANDBY_SCAN_INTERVAL
        self.lights_left = lights_left or []
        self.lights_right = lights_right or []
        self.lights_top = lights_top or []
        self.lights_bottom = lights_bottom or []
        self.lights_all = lights_all or target_lights or []
        self.lights_left_bottom = lights_left_bottom or []
        self.lights_right_bottom = lights_right_bottom or []
        self.sync_enabled = False
        self.tv_on: bool = False
        self._last_color: tuple[int, int, int] = (0, 0, 0)
        self._light_states: dict[str, dict[str, Any]] = {}
        self._last_data: dict[str, Any] = {
            "online": False,
            "tv_online": False,
            "tv_on": False,
            "powerstate": "Off",
            "r": 0,
            "g": 0,
            "b": 0,
            "color_hex": "#000000",
            "sides_colors": {},
            "corner_colors": {},
            "pixels": {},
        }

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(milliseconds=scan_interval_ms),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest ambilight color and power state from TV."""
        state = await self.hass.async_add_executor_job(
            self.client.fetch_ambilight_state
        )

        online = bool(state.get("online", False))
        tv_on = bool(state.get("tv_on", False))
        powerstate = state.get("powerstate", "Off")
        raw = state.get("raw_colors")

        # 1. Handle TV powered off / Standby / Offline
        if not tv_on or not raw:
            # If TV was previously on or we have lights currently lit by Ambilight, turn them off once
            if self.tv_on or any(
                st.get("state") == "on" for st in self._light_states.values()
            ):
                _LOGGER.info(
                    "TV is off/standby (powerstate: %s). Turning off synced lights.",
                    powerstate,
                )
                await self._turn_off_all_synced_lights()

            self.tv_on = False

            # Reduce polling frequency while TV is off to reduce CPU and network overhead
            standby_interval = timedelta(milliseconds=self._standby_interval_ms)
            if self.update_interval != standby_interval:
                self.update_interval = standby_interval

            data: dict[str, Any] = {
                **self._last_data,
                "online": online,
                "tv_online": online,
                "tv_on": False,
                "powerstate": powerstate,
                "color_hex": "#000000",
            }
            self._last_data = data
            return data

        # 2. TV is turned ON
        if not self.tv_on:
            _LOGGER.info(
                "TV turned on (powerstate: %s). Resuming fast Ambilight polling.",
                powerstate,
            )
            self.tv_on = True
            fast_interval = timedelta(milliseconds=self._scan_interval_ms)
            if self.update_interval != fast_interval:
                self.update_interval = fast_interval

        side_colors = parse_ambilight_colors(raw, self.sides)
        corner_colors = extract_corner_diodes(raw)
        pixels_data = parse_ambilight_pixels(raw)
        avg_r, avg_g, avg_b = average_colors(side_colors, self.sides)

        color_hex = f"#{avg_r:02x}{avg_g:02x}{avg_b:02x}"

        data = {
            "online": True,
            "tv_online": True,
            "tv_on": True,
            "powerstate": powerstate,
            "r": avg_r,
            "g": avg_g,
            "b": avg_b,
            "color_hex": color_hex,
            "sides_colors": {k: list(v) for k, v in side_colors.items()},
            "corner_colors": {k: list(v) for k, v in corner_colors.items()},
            "left_bottom_color": list(corner_colors.get("left_bottom", [0, 0, 0])),
            "right_bottom_color": list(corner_colors.get("right_bottom", [0, 0, 0])),
            "pixels": pixels_data,
        }
        self._last_data = data
        self._last_color = (avg_r, avg_g, avg_b)

        # 3. Push colors per zone if sync is enabled
        if self.sync_enabled:
            await self._push_zone_colors(side_colors, corner_colors, (avg_r, avg_g, avg_b))

        return data

    async def _push_zone_colors(
        self,
        side_colors: dict[str, tuple[int, int, int]],
        corner_colors: dict[str, tuple[int, int, int]],
        avg_color: tuple[int, int, int],
    ) -> None:
        """Push corresponding side colors to configured zone light entities."""
        # 1. Resolve target color for each unique light entity to prevent duplicate calls per tick
        targets: dict[str, tuple[int, int, int]] = {}

        if self.lights_left_bottom and "left_bottom" in corner_colors:
            for lid in self.lights_left_bottom:
                targets[lid] = corner_colors["left_bottom"]

        if self.lights_right_bottom and "right_bottom" in corner_colors:
            for lid in self.lights_right_bottom:
                targets[lid] = corner_colors["right_bottom"]

        if self.lights_left and "left" in side_colors:
            for lid in self.lights_left:
                targets[lid] = side_colors["left"]

        if self.lights_right and "right" in side_colors:
            for lid in self.lights_right:
                targets[lid] = side_colors["right"]

        if self.lights_top and "top" in side_colors:
            for lid in self.lights_top:
                targets[lid] = side_colors["top"]

        if self.lights_bottom and "bottom" in side_colors:
            for lid in self.lights_bottom:
                targets[lid] = side_colors["bottom"]

        all_target = self.lights_all or self.target_lights
        if all_target:
            for lid in all_target:
                # Do not override specific zone color if light was already assigned above
                if lid not in targets:
                    targets[lid] = avg_color

        if not targets:
            return

        # 2. Filter commands: don't send if light already off or color hasn't changed
        lights_to_turn_off: list[str] = []
        lights_to_turn_on: dict[tuple[int, int, int, int], list[str]] = {}

        for light_id, (r, g, b) in targets.items():
            last = self._light_states.get(light_id)

            if r == 0 and g == 0 and b == 0:
                # Target is OFF: skip if already off!
                if last is None or last.get("state") != "off":
                    lights_to_turn_off.append(light_id)
            else:
                max_c = max(r, g, b)
                calc_brightness = min(255, max(1, int(max_c * self.brightness_factor)))

                # Target is ON: check if color and brightness changed beyond threshold
                if last is not None and last.get("state") == "on":
                    last_r, last_g, last_b = last.get("rgb", (0, 0, 0))
                    last_br = last.get("brightness", 0)

                    delta = max(
                        abs(r - last_r),
                        abs(g - last_g),
                        abs(b - last_b),
                        abs(calc_brightness - last_br),
                    )

                    if delta <= self.color_threshold:
                        # Color unchanged (or noise within threshold): skip!
                        continue

                key = (r, g, b, calc_brightness)
                lights_to_turn_on.setdefault(key, []).append(light_id)

        # 3. Batch execute light.turn_off
        if lights_to_turn_off:
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {
                        "entity_id": lights_to_turn_off,
                        "transition": self.transition,
                    },
                    blocking=False,
                )
                for lid in lights_to_turn_off:
                    self._light_states[lid] = {
                        "state": "off",
                        "rgb": (0, 0, 0),
                        "brightness": 0,
                    }
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Failed to turn off lights %s: %s", lights_to_turn_off, err)

        # 4. Batch execute light.turn_on grouped by (r, g, b, brightness)
        for (r, g, b, brightness), light_group in lights_to_turn_on.items():
            service_data = {
                "entity_id": light_group,
                "rgb_color": [r, g, b],
                "brightness": brightness,
                "transition": self.transition,
            }
            try:
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    service_data,
                    blocking=False,
                )
                for lid in light_group:
                    self._light_states[lid] = {
                        "state": "on",
                        "rgb": (r, g, b),
                        "brightness": brightness,
                    }
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Failed to update lights %s: %s", light_group, err)

    async def _turn_off_all_synced_lights(self) -> None:
        """Turn off any lights currently illuminated by Ambilight once."""
        lights_to_turn_off = [
            light_id
            for light_id, state in self._light_states.items()
            if state.get("state") == "on"
        ]
        if not lights_to_turn_off:
            return

        try:
            await self.hass.services.async_call(
                "light",
                "turn_off",
                {
                    "entity_id": lights_to_turn_off,
                    "transition": self.transition,
                },
                blocking=False,
            )
            for lid in lights_to_turn_off:
                self._light_states[lid] = {
                    "state": "off",
                    "rgb": (0, 0, 0),
                    "brightness": 0,
                }
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Failed to turn off synced lights %s: %s", lights_to_turn_off, err)

    def enable_sync(self) -> None:
        """Enable color synchronization to lights."""
        self.sync_enabled = True
        self._light_states.clear()
        _LOGGER.info("Ambilight sync enabled")

    def disable_sync(self) -> None:
        """Disable color synchronization to lights."""
        self.sync_enabled = False
        self._light_states.clear()
        _LOGGER.info("Ambilight sync disabled")

    def update_zone_lights(
        self,
        lights_left_bottom: list[str],
        lights_right_bottom: list[str],
        lights_left: list[str],
        lights_right: list[str],
        lights_top: list[str],
        lights_bottom: list[str],
        lights_all: list[str],
    ) -> None:
        """Update zone light entity mappings."""
        self.lights_left_bottom = lights_left_bottom
        self.lights_right_bottom = lights_right_bottom
        self.lights_left = lights_left
        self.lights_right = lights_right
        self.lights_top = lights_top
        self.lights_bottom = lights_bottom
        self.lights_all = lights_all
        self.target_lights = lights_all
        self._light_states.clear()

    def update_sides(self, sides: list[str]) -> None:
        """Update which screen sides to use for averaging."""
        self.sides = sides

    def update_brightness_factor(self, factor: float) -> None:
        """Update the brightness multiplier."""
        self.brightness_factor = factor
        self._light_states.clear()

    def update_color_threshold(self, threshold: int) -> None:
        """Update color change threshold."""
        self.color_threshold = threshold
        self._light_states.clear()

    def update_scan_interval(self, interval_ms: int) -> None:
        """Update scan interval dynamically in milliseconds."""
        self._scan_interval_ms = interval_ms
        if self.tv_on:
            self.update_interval = timedelta(milliseconds=interval_ms)

    def update_transition(self, transition: float) -> None:
        """Update transition time in seconds."""
        self.transition = transition
