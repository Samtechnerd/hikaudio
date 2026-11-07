"""HikAudio media player: announcements on one Hikvision door station speaker."""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import time

import aiohttp

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.components.media_player.browse_media import async_process_play_media_url
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_HA_URL, CONF_MAX_GAIN, CONF_MAX_SECONDS, CONF_TOKEN, CONF_URL,
    DEFAULT_MAX_GAIN, DEFAULT_MAX_SECONDS, SIGNAL_PLAYED,
)
from .entity import HikAudioEntity, setup_dynamic

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    setup_dynamic(entry, async_add_entities, HikAudioPlayer)


def _cleanup(folder):
    for old in glob.glob(os.path.join(folder, "gate_say_*")):
        try:
            if time.time() - os.path.getmtime(old) > 600:
                os.remove(old)
        except OSError:
            pass


class HikAudioPlayer(HikAudioEntity, MediaPlayerEntity, RestoreEntity):
    """Plays announcements on one door station speaker. The volume slider is a software gain."""

    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.BROWSE_MEDIA
        | MediaPlayerEntityFeature.STOP
    )

    def __init__(self, coordinator, entry, device):
        super().__init__(coordinator, entry, device)
        self._attr_unique_id = "%s_%s" % (entry.entry_id, device)
        self._attr_state = MediaPlayerState.IDLE
        self._attr_volume_level = 1.0
        self._lock = asyncio.Lock()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.attributes.get("volume_level") is not None:
            self._attr_volume_level = float(last.attributes["volume_level"])

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def async_set_volume_level(self, volume):
        self._attr_volume_level = max(0.0, min(1.0, volume))
        self.async_write_ha_state()

    async def _stop_remote(self):
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                self._entry.data[CONF_URL].rstrip("/") + "/stop",
                json={"device": self._device},
                headers={"X-Token": self._entry.data[CONF_TOKEN]},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.exception("HikAudio could not stop %s", self._device)

    async def async_media_stop(self):
        await self._stop_remote()

    async def async_play_media(self, media_type, media_id, **kwargs):
        if self._lock.locked():
            # Something is already playing: end it so this one starts now.
            await self._stop_remote()
        async with self._lock:
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()
            try:
                await self._play(media_id)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("HikAudio could not play %s on %s", media_id, self._device)
            finally:
                self._attr_state = MediaPlayerState.IDLE
                self.async_write_ha_state()

    async def _play(self, media_id):
        gain = self._attr_volume_level * float(self._entry.options.get(CONF_MAX_GAIN, DEFAULT_MAX_GAIN))
        if gain <= 0:
            return
        hass = self.hass
        if media_source.is_media_source_id(media_id):
            media = await media_source.async_resolve_media(hass, media_id, self.entity_id)
            url = media.url
        else:
            url = media_id
        # Media files need a signed URL, otherwise HA answers 401 Unauthorized.
        url = async_process_play_media_url(hass, url, allow_relative_url=True)
        if url.startswith("/"):
            url = "http://127.0.0.1:8123" + url

        session = async_get_clientsession(hass)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            audio = await resp.read()

        www = hass.config.path("www")
        await hass.async_add_executor_job(os.makedirs, www, 0o755, True)
        name = "gate_say_%d.ulaw" % int(time.time() * 1000)
        path = os.path.join(www, name)
        # Cap music length; speech (text-to-speech) is never cut.
        is_speech = "tts" in media_id.lower()
        limit = [] if is_speech else [
            "-t", str(int(self._entry.options.get(CONF_MAX_SECONDS, DEFAULT_MAX_SECONDS)))
        ]
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-y", "-i", "pipe:0", *limit,
            "-af", "volume=%.3f,alimiter=limit=0.97" % gain,
            "-ar", "8000", "-ac", "1", "-f", "mulaw", path,
            stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(audio)
        if proc.returncode:
            raise RuntimeError("ffmpeg failed: %s" % err.decode(errors="replace"))

        base = self._entry.data[CONF_URL].rstrip("/")
        ha_url = self._entry.data[CONF_HA_URL].rstrip("/")
        async with session.post(
            base + "/say",
            json={"url": ha_url + "/local/" + name, "device": self._device},
            headers={"X-Token": self._entry.data[CONF_TOKEN]},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError("HikAudio add-on said %s: %s" % (resp.status, body[:200]))
        async_dispatcher_send(hass, SIGNAL_PLAYED % self._attr_unique_id)
        await hass.async_add_executor_job(_cleanup, www)
