"""Shared base entity for HikAudio."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def pretty(device):
    return device.replace("_", " ").title()


def setup_dynamic(entry, async_add_entities, factory):
    """Create entities for every device the add-on reports, including ones added later."""
    coordinator = entry.runtime_data
    known = set()

    @callback
    def _add():
        new = [d for d in (coordinator.data or {}) if d not in known]
        if new:
            known.update(new)
            async_add_entities([factory(coordinator, entry, d) for d in new])

    _add()
    entry.async_on_unload(coordinator.async_add_listener(_add))


class HikAudioEntity(CoordinatorEntity):
    """One entity belonging to one door station."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, device):
        super().__init__(coordinator)
        self._entry = entry
        self._device = device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "%s_%s" % (entry.entry_id, device))},
            name="HikAudio " + pretty(device),
            manufacturer="Hikvision",
            model="Door station (voice talk)",
        )

    @property
    def _info(self):
        return (self.coordinator.data or {}).get(self._device) or {}

    @property
    def available(self):
        return self.coordinator.last_update_success and bool(self._info.get("online"))
