"""Config flow for Hue Ambilight integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    DOMAIN,
    CONF_TV_IP,
    CONF_TV_PORT,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_LIGHTS,
    CONF_LIGHTS_LEFT,
    CONF_LIGHTS_RIGHT,
    CONF_LIGHTS_TOP,
    CONF_LIGHTS_BOTTOM,
    CONF_LIGHTS_ALL,
    CONF_SCAN_INTERVAL,
    CONF_SIDES,
    CONF_TRANSITION,
    CONF_BRIGHTNESS_FACTOR,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SIDES,
    DEFAULT_TRANSITION,
    DEFAULT_BRIGHTNESS_FACTOR,
    SIDES,
    MIN_SCAN_INTERVAL_MS,
    MAX_SCAN_INTERVAL_MS,
)
from .philips_tv import PhilipsTVClient, PhilipsTVOfflineError, PhilipsTVAuthError, PhilipsTVError

_LOGGER = logging.getLogger(__name__)

STEP_TV_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TV_IP): str,
        vol.Optional(CONF_TV_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)

STEP_PIN_SCHEMA = vol.Schema(
    {
        vol.Required("pin"): str,
    }
)


class HueAmbilightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Hue Ambilight."""

    VERSION = 1

    def __init__(self) -> None:
        self._tv_ip: str = ""
        self._tv_port: int = DEFAULT_PORT
        self._client: PhilipsTVClient | None = None
        self._pair_auth_key: str = ""
        self._pair_timestamp: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Enter TV IP address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._tv_ip = user_input[CONF_TV_IP].strip()
            self._tv_port = user_input.get(CONF_TV_PORT, DEFAULT_PORT)

            # Check for duplicate
            await self.async_set_unique_id(f"{self._tv_ip}:{self._tv_port}")
            self._abort_if_unique_id_configured()

            # Try connecting to TV
            client = PhilipsTVClient(self._tv_ip, self._tv_port)
            try:
                auth_key, timestamp = await self.hass.async_add_executor_job(client.pair_request)
                self._pair_auth_key = auth_key
                self._pair_timestamp = timestamp
                self._client = client
                _LOGGER.debug(
                    "pair/request OK: auth_key_len=%d timestamp=%s",
                    len(self._pair_auth_key), self._pair_timestamp,
                )
                return await self.async_step_pair()
            except PhilipsTVOfflineError:
                errors["base"] = "cannot_connect"
            except PhilipsTVError as err:
                _LOGGER.error("Pairing request failed: %s", err)
                errors["base"] = "pair_request_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_TV_SCHEMA,
            errors=errors,
            description_placeholders={"port": str(DEFAULT_PORT)},
        )

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Enter PIN shown on TV screen."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input["pin"].strip()
            try:
                username, password = await self.hass.async_add_executor_job(
                    self._client.pair_grant,
                    pin,
                    self._pair_auth_key,
                    self._pair_timestamp,
                )
                # Save credentials and proceed to light selection
                self._client.username = username
                self._client.password = password
                return await self.async_step_lights()
            except PhilipsTVAuthError:
                errors["base"] = "invalid_pin"
            except PhilipsTVError as err:
                _LOGGER.error("Pairing grant failed: %s", err)
                errors["base"] = "pair_grant_failed"

        return self.async_show_form(
            step_id="pair",
            data_schema=STEP_PIN_SCHEMA,
            errors=errors,
            description_placeholders={"tv_ip": self._tv_ip},
        )

    async def async_step_lights(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 3: Select target light entities per zone."""
        if user_input is not None:
            data = {
                CONF_TV_IP: self._tv_ip,
                CONF_TV_PORT: self._tv_port,
                CONF_USERNAME: self._client.username,
                CONF_PASSWORD: self._client.password,
                CONF_LIGHTS_LEFT: user_input.get(CONF_LIGHTS_LEFT, []),
                CONF_LIGHTS_RIGHT: user_input.get(CONF_LIGHTS_RIGHT, []),
                CONF_LIGHTS_TOP: user_input.get(CONF_LIGHTS_TOP, []),
                CONF_LIGHTS_BOTTOM: user_input.get(CONF_LIGHTS_BOTTOM, []),
                CONF_LIGHTS_ALL: user_input.get(CONF_LIGHTS_ALL, []),
                CONF_LIGHTS: user_input.get(CONF_LIGHTS_ALL, []),
                CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                CONF_SIDES: DEFAULT_SIDES,
                CONF_TRANSITION: user_input.get(CONF_TRANSITION, DEFAULT_TRANSITION),
                CONF_BRIGHTNESS_FACTOR: user_input.get(CONF_BRIGHTNESS_FACTOR, DEFAULT_BRIGHTNESS_FACTOR),
            }
            return self.async_create_entry(
                title=f"Ambilight Sync ({self._tv_ip})",
                data=data,
            )

        # Build list of available light entities
        ent_reg = er.async_get(self.hass)
        light_entities = [
            selector.SelectOptionDict(value=e.entity_id, label=e.entity_id)
            for e in ent_reg.entities.values()
            if e.domain == "light"
        ]

        light_select = selector.selector(
            {"select": {"options": light_entities, "multiple": True}}
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_LIGHTS_LEFT, default=[]): light_select,
                vol.Optional(CONF_LIGHTS_RIGHT, default=[]): light_select,
                vol.Optional(CONF_LIGHTS_TOP, default=[]): light_select,
                vol.Optional(CONF_LIGHTS_BOTTOM, default=[]): light_select,
                vol.Optional(CONF_LIGHTS_ALL, default=[]): light_select,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_MS, max=MAX_SCAN_INTERVAL_MS)
                ),
                vol.Optional(CONF_TRANSITION, default=DEFAULT_TRANSITION): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=10)
                ),
                vol.Optional(CONF_BRIGHTNESS_FACTOR, default=DEFAULT_BRIGHTNESS_FACTOR): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=2.0)
                ),
            }
        )

        return self.async_show_form(
            step_id="lights",
            data_schema=schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HueAmbilightOptionsFlow:
        """Return the options flow handler."""
        return HueAmbilightOptionsFlow(config_entry)


class HueAmbilightOptionsFlow(config_entries.OptionsFlow):
    """Handle options (reconfigure lights, interval, sides, etc.)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show options form when user clicks 'Configure' on the Device page."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}

        ent_reg = er.async_get(self.hass)
        light_entities = [
            selector.SelectOptionDict(value=e.entity_id, label=e.entity_id)
            for e in ent_reg.entities.values()
            if e.domain == "light"
        ]

        light_select = selector.selector(
            {"select": {"options": light_entities, "multiple": True}}
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_LIGHTS_LEFT, default=current.get(CONF_LIGHTS_LEFT, [])): light_select,
                vol.Optional(CONF_LIGHTS_RIGHT, default=current.get(CONF_LIGHTS_RIGHT, [])): light_select,
                vol.Optional(CONF_LIGHTS_TOP, default=current.get(CONF_LIGHTS_TOP, [])): light_select,
                vol.Optional(CONF_LIGHTS_BOTTOM, default=current.get(CONF_LIGHTS_BOTTOM, [])): light_select,
                vol.Optional(CONF_LIGHTS_ALL, default=current.get(CONF_LIGHTS_ALL, current.get(CONF_LIGHTS, []))): light_select,
                vol.Optional(CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL_MS, max=MAX_SCAN_INTERVAL_MS)
                ),
                vol.Optional(CONF_TRANSITION, default=current.get(CONF_TRANSITION, DEFAULT_TRANSITION)): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=10)
                ),
                vol.Optional(CONF_BRIGHTNESS_FACTOR, default=current.get(CONF_BRIGHTNESS_FACTOR, DEFAULT_BRIGHTNESS_FACTOR)): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=2.0)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
