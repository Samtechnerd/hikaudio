"""Config flow for HikAudio."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_HA_URL, CONF_MAX_GAIN, CONF_MAX_SECONDS, CONF_TEST_MESSAGE, CONF_TOKEN, CONF_TTS_ENTITY, CONF_URL,
    DEFAULT_HA_URL, DEFAULT_MAX_GAIN, DEFAULT_MAX_SECONDS, DEFAULT_TEST_MESSAGE, DEFAULT_TTS_ENTITY, DEFAULT_URL, DOMAIN,
)


async def _probe(hass, url, token):
    """Return None when the add-on answers with at least one device, else an error key."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            url + "/devices", headers={"X-Token": token}, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 403:
                return "invalid_auth"
            if resp.status != 200:
                return "cannot_connect"
            body = await resp.json()
            if not body.get("devices"):
                return "no_devices"
    except (aiohttp.ClientError, TimeoutError):
        return "cannot_connect"
    return None


class HikAudioConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            if url.endswith("/say"):
                url = url[:-4]
            error = await _probe(self.hass, url, user_input[CONF_TOKEN])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="HikAudio",
                    data={
                        CONF_URL: url,
                        CONF_TOKEN: user_input[CONF_TOKEN],
                        CONF_HA_URL: user_input[CONF_HA_URL].strip().rstrip("/"),
                    },
                )
        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL)): str,
                vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN, "")): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_HA_URL, default=defaults.get(CONF_HA_URL, DEFAULT_HA_URL)): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HikAudioOptionsFlow()


class HikAudioOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_MAX_GAIN, default=o.get(CONF_MAX_GAIN, DEFAULT_MAX_GAIN)): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=8.0)
                ),
                vol.Required(CONF_MAX_SECONDS, default=o.get(CONF_MAX_SECONDS, DEFAULT_MAX_SECONDS)): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=115)
                ),
                vol.Required(CONF_TTS_ENTITY, default=o.get(CONF_TTS_ENTITY, DEFAULT_TTS_ENTITY)): str,
                vol.Required(CONF_TEST_MESSAGE, default=o.get(CONF_TEST_MESSAGE, DEFAULT_TEST_MESSAGE)): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
