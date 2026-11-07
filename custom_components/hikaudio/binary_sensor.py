"""HikAudio online sensor."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import HikAudioEntity, setup_dynamic


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(entry, async_add_entities, HikAudioOnline)


class HikAudioOnline(HikAudioEntity, BinarySensorEntity):
    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, entry, device):
        super().__init__(coordinator, entry, device)
        self._attr_unique_id = "%s_%s_online" % (entry.entry_id, device)

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def is_on(self):
        return bool(self._info.get("online"))
