"""Polls the HikAudio add-on for the status of each door station."""
from __future__ import annotations

from datetime import timedelta
import logging

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_TOKEN, CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HikAudioCoordinator(DataUpdateCoordinator):
    """Data is a dict: device name -> {host, online}."""

    def __init__(self, hass, entry):
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry,
            update_interval=timedelta(seconds=30),
        )
        self._entry = entry

    async def _async_update_data(self):
        base = self._entry.data[CONF_URL].rstrip("/")
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                base + "/status",
                headers={"X-Token": self._entry.data[CONF_TOKEN]},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 403:
                    raise UpdateFailed("The HikAudio add-on rejected the token")
                resp.raise_for_status()
                body = await resp.json()
        except UpdateFailed:
            raise
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed("Cannot reach the HikAudio add-on: %s" % err) from err
        return body.get("devices", {})
