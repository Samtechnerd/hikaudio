FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ffmpeg libstdc++6 libuuid1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY hiksdk/lib /opt/hiksdk/lib
COPY voice_say /opt/gate_talk/voice_say
COPY voice_live /opt/gate_talk/voice_live
COPY server.py ui.html /opt/gate_talk/
RUN chmod +x /opt/gate_talk/voice_say /opt/gate_talk/voice_live

ENV LD_LIBRARY_PATH=/opt/hiksdk/lib:/opt/hiksdk/lib/HCNetSDKCom

CMD ["python3", "-I", "/opt/gate_talk/server.py"]
