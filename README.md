# HikAudio for intercoms

Play text-to-speech, music and live voice through the speaker of Hikvision door stations from Home Assistant.
Tested on DS-KD8003-IME1 and DS-KV6113-WPE1(C). *Unofficial. Not affiliated with or endorsed by Hikvision.*

Hikvision's ISAPI audio, SIP and RTSP back-channel routes were silent or refused on these models. Only the
Hikvision Device Network SDK voice talk (`NET_DVR_StartVoiceCom_MR_V30`) works, so this project wraps it in a
small Home Assistant add-on plus a UI-configured integration.

## What you get
- **Integration** (`custom_components/hikaudio`): one device per door station with a media player
  (play media, Browse media, volume, stop), a test button, last-announcement and online sensors, and a
  `hikaudio.say` service.
- **Add-on** (`addon`): the service that talks to the door stations, plus a sidebar panel with live video,
  hold-to-talk and door-microphone listening. amd64 only.
- **Volume** is a software gain applied before sending, so the intercom's own settings are never changed.
- Music is cut at 30 seconds by default (option in the integration); speech is never cut.

## Install
1. Get the Hikvision **HCNetSDK Linux 64-bit** (tested with V6.1.11.40) from Hikvision. It is not included
   here because its licence does not allow redistribution.
2. Build the two helpers against it (`helper/voice_say.cpp`, `helper/voice_live.cpp`), for example:
   `g++ -O2 -o voice_say voice_say.cpp -I<sdk>/incEn -L<sdk>/lib -lhcnetsdk -lpthread`
   (same for `voice_live`).
3. Copy `addon/` to your Home Assistant `addons` share as `gate_talk_addon/`, then add `voice_say`, `voice_live`
   and the SDK `lib` folder as `hiksdk/lib`. Update the add-on list, install **HikAudio**, set a **token** and one
   entry per door station under **devices**, and start it.
4. Copy `custom_components/hikaudio` into your HA `config/custom_components/`, restart HA, then
   Settings, Devices and Services, Add integration, **HikAudio**. Use the same token.

The add-on needs `ha_url` to match how the add-on reaches Home Assistant, because audio files are fetched from
`<ha_url>/local/`.

## Notes
- Door stations allow only a few simultaneous RTSP video sessions, so the panel retries a few times.
- The panel's microphone needs https (or the HA app) and may depend on Home Assistant's frame permissions.
- Audio is sent in lockstep with the door station's microphone frames, which is the only mode that is audible.
