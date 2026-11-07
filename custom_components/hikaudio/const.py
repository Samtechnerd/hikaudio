"""Constants for HikAudio for intercoms (unofficial, not affiliated with Hikvision)."""

DOMAIN = "hikaudio"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_HA_URL = "ha_url"
CONF_MAX_GAIN = "max_gain"
CONF_TEST_MESSAGE = "test_message"
CONF_TTS_ENTITY = "tts_entity"
CONF_MAX_SECONDS = "max_seconds"
DEFAULT_MAX_SECONDS = 30

DEFAULT_URL = "http://192.168.2.112:8765"
DEFAULT_HA_URL = "http://192.168.2.112:8123"
DEFAULT_MAX_GAIN = 3.0
DEFAULT_TEST_MESSAGE = "This is a test announcement from Home Assistant."
DEFAULT_TTS_ENTITY = "tts.piper"

PLATFORMS = ["media_player", "button", "sensor", "binary_sensor"]
SIGNAL_PLAYED = "hikaudio_played_%s"
