"""HikAudio test announcement button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import CONF_TEST_MESSAGE, CONF_TTS_ENTITY, DEFAULT_TEST_MESSAGE, DEFAULT_TTS_ENTITY, DOMAIN
from .entity import HikAudioEntity, setup_dynamic


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(entry, async_add_entities, HikAudioTestButton)


class HikAudioTestButton(HikAudioEntity, ButtonEntity):
    _attr_translation_key = "test_announcement"

    def __init__(self, coordinator, entry, device):
        super().__init__(coordinator, entry, device)
        self._attr_unique_id = "%s_%s_test" % (entry.entry_id, device)

    async def async_press(self):
        reg = er.async_get(self.hass)
        player = reg.async_get_entity_id("media_player", DOMAIN, "%s_%s" % (self._entry.entry_id, self._device))
        if player is None:
            raise HomeAssistantError("The HikAudio media player for this door station was not found")
        opts = self._entry.options
        await self.hass.services.async_call(
            "tts", "speak",
            {
                "entity_id": opts.get(CONF_TTS_ENTITY, DEFAULT_TTS_ENTITY),
                "media_player_entity_id": player,
                "message": opts.get(CONF_TEST_MESSAGE, DEFAULT_TEST_MESSAGE),
            },
            blocking=True,
        )
