"""HikAudio for intercoms: Hikvision door station speakers as media players (unofficial)."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import CONF_TTS_ENTITY, DEFAULT_TTS_ENTITY, DOMAIN, PLATFORMS
from .coordinator import HikAudioCoordinator

SERVICE_SAY = "say"
SAY_SCHEMA = vol.Schema(
    {
        vol.Required("message"): cv.string,
        vol.Required("entity_id"): cv.entity_ids,
        vol.Optional("tts_entity"): cv.entity_id,
    }
)


async def async_setup_entry(hass, entry):
    coordinator = HikAudioCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))

    if not hass.services.has_service(DOMAIN, SERVICE_SAY):

        async def _say(call):
            tts_entity = call.data.get("tts_entity") or entry.options.get(CONF_TTS_ENTITY, DEFAULT_TTS_ENTITY)
            await hass.services.async_call(
                "tts", "speak",
                {
                    "entity_id": tts_entity,
                    "media_player_entity_id": call.data["entity_id"],
                    "message": call.data["message"],
                },
                blocking=True,
            )

        hass.services.async_register(DOMAIN, SERVICE_SAY, _say, schema=SAY_SCHEMA)
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and len(hass.config_entries.async_loaded_entries(DOMAIN)) <= 1:
        hass.services.async_remove(DOMAIN, SERVICE_SAY)
    return ok
