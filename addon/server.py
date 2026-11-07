#!/usr/bin/env python3
"""HikAudio add-on service (multi-device).

Port 8765 (Home Assistant integration, needs header X-Token):
    POST /say   {"url": "<ha_url>/local/gate_say_<n>.ulaw", "device": "gate"}  play audio
    POST /stop  {"device": "gate"}                                              end playback now
    GET  /devices, GET /status
Port 8099 (the sidebar panel, reached through Home Assistant ingress; Home Assistant has
already signed the user in, so only the Supervisor's address is accepted):
    GET  /                      the web page
    GET  /video?device=gate     live video (MJPEG, from the door station's RTSP stream)
    POST /live/start?device=    open a two-way voice session
    POST /live/audio?device=    mic audio from the browser (raw u-law, 8 kHz mono)
    GET  /live/listen?device=   door station mic audio (raw u-law stream)
    POST /live/stop?device=
Settings come from the add-on options (/data/options.json); passwords are never logged
or passed on the helper's argv.
"""
import collections, ipaddress, json, os, signal, socket, subprocess, tempfile, threading, time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

PORT = 8765
UI_PORT = 8099
INGRESS_IPS = ("172.30.32.2", "127.0.0.1")
HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.environ.get("HIKAUDIO_SAY", "/opt/gate_talk/voice_say")
LIVE_HELPER = os.environ.get("HIKAUDIO_LIVE", "/opt/gate_talk/voice_live")
LIVE_MAX_SECONDS = 300

OPTS = json.load(open(os.environ.get("HIKAUDIO_OPTIONS", "/data/options.json")))
TOKEN = OPTS.get("token", "")
URL_PREFIX = OPTS["ha_url"].rstrip("/") + "/local/gate_say_"


def key(name):
    return name.strip().lower().replace(" ", "_")


DEVICES = {key(d["name"]): d for d in OPTS.get("devices", [])}
LOCKS = {k: threading.Lock() for k in DEVICES}
DEFAULT = next(iter(DEVICES), None)
PROCS = {}       # device -> running /say helper process
STOPPED = set()  # devices whose announcement was ended by /stop
LIVE = {}        # device -> live session (see live_start)


def allowed(ip):
    # Only callers on the Home Assistant / add-on network or the private LAN.
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def device_env(d):
    return dict(os.environ, HIK_HOST=d["host"], HIK_PORT=str(d["port"]),
                HIK_USER=d["user"], HIK_PASS=d["password"])


class Live:
    """One two-way voice session: voice_live helper, stdin = browser audio, stdout = door mic."""

    def __init__(self, name):
        self.name = name
        d = DEVICES[name]
        self.proc = subprocess.Popen(
            [LIVE_HELPER, str(d.get("channel", 1))], env=device_env(d),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.chunks = collections.deque(maxlen=100)  # door mic audio waiting for a listener
        self.cond = threading.Condition()
        self.ready = threading.Event()
        self.error = ""
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self.timer = threading.Timer(LIVE_MAX_SECONDS, self.kill)
        self.timer.daemon = True
        self.timer.start()

    def _read_out(self):
        while True:
            data = self.proc.stdout.read(160)
            if not data:
                break
            with self.cond:
                self.chunks.append(data)
                self.cond.notify_all()
        self.proc.wait()
        self.timer.cancel()
        self.ready.set()
        with self.cond:
            self.cond.notify_all()
        LIVE.pop(self.name, None)
        LOCKS[self.name].release()

    def _read_err(self):
        for line in self.proc.stderr:
            line = line.decode(errors="replace").strip()
            if line.startswith("talk session open"):
                self.ready.set()
            elif line.startswith(("login failed", "StartVoiceCom")):
                self.error = line

    def alive(self):
        return self.proc.poll() is None

    def kill(self):
        try:
            self.proc.kill()
        except OSError:
            pass


def live_start(name):
    """Return (session, error). Fails fast when the door station is busy or unreachable."""
    if name in LIVE and LIVE[name].alive():
        return LIVE[name], None
    if not LOCKS[name].acquire(blocking=False):
        return None, "door station is busy playing an announcement"
    try:
        s = Live(name)
    except OSError as e:
        LOCKS[name].release()
        return None, "could not start helper: %s" % e
    LIVE[name] = s
    s.ready.wait(timeout=8)
    if not s.alive():
        return None, s.error or "door station refused the voice session"
    return s, None


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("%s %s" % (self.client_address[0], fmt % args), flush=True)

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorised(self):
        return bool(TOKEN) and allowed(self.client_address[0]) and self.headers.get("X-Token") == TOKEN

    def query_device(self):
        q = parse_qs(urlparse(self.path).query)
        name = key((q.get("device") or [DEFAULT or ""])[0])
        return name if name in DEVICES else None

    def do_GET(self):
        if not self.authorised():
            return self.reply(403, {"ok": False, "error": "forbidden"})
        path = urlparse(self.path).path
        if path == "/devices":
            return self.reply(200, {"ok": True, "devices": list(DEVICES)})
        if path == "/status":
            # Cheap reachability check (TCP connect to the SDK port; no login, so it never
            # interrupts an announcement).
            status = {}
            for k, d in DEVICES.items():
                try:
                    socket.create_connection((d["host"], int(d["port"])), timeout=2).close()
                    online = True
                except OSError:
                    online = False
                status[k] = {"host": d["host"], "online": online}
            return self.reply(200, {"ok": True, "devices": status})
        if self.ui and path in ("/", "/index.html"):
            return self.page()
        if self.ui and path == "/video":
            return self.video()
        if self.ui and path == "/live/listen":
            return self.listen()
        return self.reply(404, {"ok": False, "error": "not found"})

    ui = False

    def page(self):
        body = open(os.path.join(HERE, "ui.html"), "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def video(self):
        name = self.query_device()
        if not name:
            return self.reply(404, {"ok": False, "error": "unknown device"})
        d = DEVICES[name]
        path = d.get("rtsp_path") or "Streaming/Channels/102"
        url = "rtsp://%s:%s@%s:%s/%s" % (quote(d["user"], safe=""), quote(d["password"], safe=""),
                                         d["host"], d.get("rtsp_port", 554), path)
        cmd = ["ffmpeg", "-loglevel", "error", "-allowed_media_types", "video", "-rtsp_transport", "tcp",
               "-i", url, "-an", "-vf", "fps=6,scale=640:-2", "-q:v", "6", "-f", "mpjpeg", "pipe:1"]
        # The door station allows only a few RTSP sessions at once (other cameras and recorders use
        # them too), so it sometimes answers "500" for a moment. Retry a few times.
        p, first = None, b""
        for attempt in range(5):
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            first = p.stdout.read(4096)
            if first:
                break
            p.wait()
            time.sleep(1.5)
        if not first:
            return self.reply(502, {"ok": False, "error": "no video from the door station (it may be out of video sessions)"})
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=ffmpeg")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(first)
            while True:
                data = p.stdout.read(16384)
                if not data:
                    break
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            # SIGINT lets ffmpeg send RTSP TEARDOWN, so the door station frees the session at once.
            p.send_signal(signal.SIGINT)
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    def listen(self):
        name = self.query_device()
        s = LIVE.get(name) if name else None
        if not s or not s.alive():
            return self.reply(409, {"ok": False, "error": "no live session"})
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                with s.cond:
                    if not s.chunks and s.alive():
                        s.cond.wait(timeout=1)
                    data = b"".join(s.chunks)
                    s.chunks.clear()
                if data:
                    self.wfile.write(data)
                    self.wfile.flush()
                elif not s.alive():
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_POST(self):
        if not self.authorised():
            return self.reply(403, {"ok": False, "error": "forbidden"})
        path = urlparse(self.path).path
        if path == "/stop":
            return self.stop()
        if self.ui and path.startswith("/live/"):
            return self.live(path)
        if path != "/say":
            return self.reply(404, {"ok": False, "error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n))
            url = body["url"]
        except Exception:
            return self.reply(400, {"ok": False, "error": "bad request"})
        name = key(body.get("device") or DEFAULT or "")
        if name not in DEVICES:
            return self.reply(404, {"ok": False, "error": "unknown device %r; known: %s" % (name, ", ".join(DEVICES))})
        if not (url.startswith(URL_PREFIX) and url.endswith(".ulaw")):
            return self.reply(400, {"ok": False, "error": "url not allowed"})
        d = DEVICES[name]
        with LOCKS[name]:
            with tempfile.NamedTemporaryFile(suffix=".ulaw", delete=True) as tmp:
                try:
                    tmp.write(urllib.request.urlopen(url, timeout=10).read())
                    tmp.flush()
                except Exception as e:
                    return self.reply(502, {"ok": False, "error": "fetch failed: %s" % e})
                p = subprocess.Popen([HELPER, tmp.name, str(d.get("channel", 1))], env=device_env(d),
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                PROCS[name] = p
                try:
                    _, err = p.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    p.kill()
                    _, err = p.communicate()
                finally:
                    PROCS.pop(name, None)
        if name in STOPPED:
            STOPPED.discard(name)
            return self.reply(200, {"ok": True, "device": name, "stopped": True})
        ok = p.returncode == 0
        # Keep only the helper's own summary lines (drop SDK noise).
        lines = [l for l in err.splitlines() if l.startswith(("login", "talk", "sent", "done", "StartVoice", "send"))]
        self.reply(200 if ok else 500, {"ok": ok, "device": name, "log": " | ".join(lines)[-300:]})

    def live(self, path):
        name = self.query_device()
        if not name:
            return self.reply(404, {"ok": False, "error": "unknown device"})
        if path == "/live/start":
            s, err = live_start(name)
            return self.reply(200 if s else 503, {"ok": bool(s), "error": err})
        s = LIVE.get(name)
        if path == "/live/stop":
            if s:
                try:
                    s.proc.stdin.close()
                except OSError:
                    pass
                s.kill()
            return self.reply(200, {"ok": True})
        if path == "/live/audio":
            if not s or not s.alive():
                return self.reply(409, {"ok": False, "error": "no live session"})
            data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                s.proc.stdin.write(data)
                s.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                return self.reply(409, {"ok": False, "error": "session ended"})
            return self.reply(200, {"ok": True})
        return self.reply(404, {"ok": False, "error": "not found"})

    def stop(self):
        """POST /stop {"device": "gate"}: end the announcement or live call on that door station."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            return self.reply(400, {"ok": False, "error": "bad request"})
        name = key(body.get("device") or DEFAULT or "")
        if name not in DEVICES:
            return self.reply(404, {"ok": False, "error": "unknown device %r" % name})
        live = LIVE.get(name)
        if live and live.alive():
            live.kill()
            return self.reply(200, {"ok": True, "device": name, "stopped": True})
        p = PROCS.get(name)
        if p is None or p.poll() is not None:
            return self.reply(200, {"ok": True, "device": name, "stopped": False})
        STOPPED.add(name)
        p.kill()
        self.reply(200, {"ok": True, "device": name, "stopped": True})


class UI(H):
    """Panel traffic arrives through Home Assistant ingress, which has already signed the user in."""
    ui = True

    def authorised(self):
        return self.client_address[0] in INGRESS_IPS


if __name__ == "__main__":
    if not TOKEN:
        print("Set 'token' in the add-on options, then restart.", flush=True)
    for k, d in DEVICES.items():
        print("device %s -> %s:%s%s" % (k, d["host"], d["port"], "" if d.get("password") else "  (PASSWORD MISSING)"), flush=True)
    print("HikAudio service on :%d (audio from %s*) and panel on :%d" % (PORT, URL_PREFIX, UI_PORT), flush=True)
    ui_server = ThreadingHTTPServer(("0.0.0.0", UI_PORT), UI)
    ui_server.daemon_threads = True
    threading.Thread(target=ui_server.serve_forever, daemon=True).start()
    main_server = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    main_server.daemon_threads = True
    main_server.serve_forever()
