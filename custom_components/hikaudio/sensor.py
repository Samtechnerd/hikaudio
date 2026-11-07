"""HikAudio last announcement sensor."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import SIGNAL_PLAYED
from .entity import HikAudioEntity, setup_dynamic


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(entry, async_add_entities, HikAudioLastAnnouncement)


class HikAudioLastAnnouncement(HikAudioEntity, SensorEntity):
    _attr_translation_key = "last_announcement"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry, device):
        super().__init__(coordinator, entry, device)
        self._key = "%s_%s" % (entry.entry_id, device)
        self._attr_unique_id = self._key + "_last"
        self._attr_native_value = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PLAYED % self._key, self._played)
        )

    @callback
    def _played(self):
        self._attr_native_value = dt_util.utcnow()
        self.async_write_ha_state()
