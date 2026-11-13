import asyncio
import json
import os
import pwd
import signal
import glob
import shutil
import re

import decky

GSR_APP_ID = "com.dec05eba.gpu_screen_recorder"
GSR_PATTERN = "gpu-screen-recorder -w"   # was "... -w screen", and it would have been the end of it and super easy and not a hassle at all, now we have to pass a connector name because the Steam Deck AMD drivers are fucking stupid
SERVICES = ("twitch", "youtube", "custom")

GST_AUDIO_SOURCE = "@DEFAULT_MONITOR@"

# Every element the pipeline in _build_gst_cmd uses (queue is core, so it's not listed).
GST_REQUIRED = (
    "pipewiresrc", "pulsesrc",
    "vapostproc", "vah264enc", "h264parse",
    "audioconvert", "audioresample", "avenc_aac", "aacparse",
    "flvmux", "rtmp2sink",
)

DEFAULT_CONFIG = {
    "twitch":  {"ingest": "rtmp://live.twitch.tv/app",        "key": ""},
    "youtube": {"ingest": "rtmp://a.rtmp.youtube.com/live2",  "key": ""},
    "custom":  {"ingest": "",                                  "key": ""},
}

QUALITY_PRESETS = {   # kbit/s
    "potato": 1000,
    "low": 2200,
    "balanced": 4500,
    "high": 6500,
    "very_high": 8000,
}
DEFAULT_QUALITY = "balanced"

# ---------- config ----------

def _config_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "config.json")

def _state_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "state.json")

def _load_state() -> dict:
    try:
        with open(_state_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_state(**updates):
    state = _load_state()          # keep whatever else is already saved
    state.update(updates)
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(_state_path(), "w") as f:
        json.dump(state, f)

def _write_default_config():
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    path = _config_path()
    with open(path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    # Contains stream keys: owned by the user, not world-readable.
    if os.geteuid() == 0:
        pw = pwd.getpwnam(decky.DECKY_USER)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    os.chmod(path, 0o600)

def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = _config_path()
    if not os.path.exists(path):
        _write_default_config()
        return cfg
    try:
        with open(path) as f:
            user_cfg = json.load(f)
        for service in SERVICES:
            section = user_cfg.get(service)
            if isinstance(section, dict):
                for k in ("ingest", "key"):
                    if isinstance(section.get(k), str):
                        cfg[service][k] = section[k]
    except Exception as e:
        decky.logger.error(f"Could not read config, using defaults: {e}")
    return cfg
# ---------- Command builders ----------
def _gst_video_encode(bitrate: int, framerate: int) -> list:
    return [
        "vapostproc", "!",
        "vah264enc", f"bitrate={bitrate}", f"key-int-max={framerate}", "!",
        "h264parse",
    ]

def _build_gst_cmd(url: str, bitrate: int, framerate: int) -> list:
    return [
        "gst-launch-1.0", "-e",
        "flvmux", "name=mux", "streamable=true", "!",
        "rtmp2sink", f"location={url}",
        "pipewiresrc", "target-object=gamescope", "do-timestamp=true", f"keepalive-time={round(1000 / framerate)}", "!", "queue", "!",
        *_gst_video_encode(bitrate, framerate), "!", "queue", "!", "mux.",
        "pulsesrc", f"device={GST_AUDIO_SOURCE}", "!", "queue", "!",
        "audioconvert", "!", "audioresample", "!",
        "avenc_aac", "bitrate=128000", "!", "aacparse", "!", "queue", "!", "mux.",
    ]

def _build_gsr_cmd(url: str, bitrate: int, framerate: int, ext: str) -> list:
    return [
        "flatpak", "run", "--command=gpu-screen-recorder", GSR_APP_ID,
        "-w", ext,
        "-f", str(framerate),
        "-a", "default_output",
        "-c", "flv",
        "-bm", "cbr",
        "-q", str(bitrate),
        "-o", url,
    ]
# ---------- process helpers ----------

def _user_ctx():
    """Env (and, only if we're root, credentials) for running as the real user."""
    pw = pwd.getpwnam(decky.DECKY_USER)
    runtime_dir = f"/run/user/{pw.pw_uid}"
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": pw.pw_dir,
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        "WAYLAND_DISPLAY": "gamescope-0",
    }
    kwargs = {}
    if os.geteuid() == 0:  # only possible if plugin.json has the "root" flag
        kwargs = {
            "user": pw.pw_uid,
            "group": pw.pw_gid,
            "extra_groups": os.getgrouplist(pw.pw_name, pw.pw_gid),
        }
    return env, kwargs

async def _exec(*cmd, extra_env=None) -> int:
    env, user_kwargs = _user_ctx()
    if extra_env:
        env.update(extra_env)
    p = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        **user_kwargs,
    )
    await p.wait()
    return p.returncode


async def _capture(*cmd) -> str:
    env, user_kwargs = _user_ctx()
    p = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        **user_kwargs,
    )
    out, _ = await p.communicate()
    return out.decode(errors="replace")


async def _probe_elements(extra_env=None) -> list:
    """Names from GST_REQUIRED that gst-inspect cannot find."""
    # First check alone: with a fresh registry it scans every plugin once,
    # and the parallel checks after it reuse the result.
    first = await _exec("gst-inspect-1.0", "--exists", GST_REQUIRED[0], extra_env=extra_env)
    rest = await asyncio.gather(
        *(_exec("gst-inspect-1.0", "--exists", e, extra_env=extra_env)
          for e in GST_REQUIRED[1:])
    )
    return [e for e, rc in zip(GST_REQUIRED, [first, *rest]) if rc != 0]


async def _bundle_key():
    """Compatibility key like '1.28-ffmpeg62', or None if it can't be worked out."""
    out = await _capture("gst-inspect-1.0", "--version")
    m = re.search(r"GStreamer (\d+\.\d+)", out)
    if not m:
        return None
    av = None
    for d in ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu"):
        for p in sorted(glob.glob(os.path.join(d, "libavcodec.so.*"))):
            mm = re.search(r"libavcodec\.so\.(\d+)", os.path.basename(p))
            if mm:
                av = mm.group(1)
                break
        if av:
            break
    if av is None:
        return None
    return f"{m.group(1)}-ffmpeg{av}"


async def _resolve_gst():
    """Decide how GStreamer can be used. Returns (missing, extra_env, note)."""
    path = _user_ctx()[0]["PATH"]
    no_tools = [
        t for t in ("gst-launch-1.0", "gst-inspect-1.0")
        if shutil.which(t, path=path) is None
    ]
    if no_tools:
        return no_tools, {}, ""

    missing = await _probe_elements()
    if not missing:
        return [], {}, ""  # the system has everything: the bundle stays unused

    key = await _bundle_key()
    bundle = os.path.join(decky.DECKY_PLUGIN_DIR, "gst-plugins", key) if key else None
    if not bundle or not os.path.isdir(bundle):
        note = f"No bundled encoder plugins for this system ({key or 'unknown GStreamer/ffmpeg version'})."
        decky.logger.warning(note)
        return missing, {}, note

    os.makedirs(decky.DECKY_PLUGIN_RUNTIME_DIR, exist_ok=True)
    extra_env = {
        "GST_PLUGIN_PATH": bundle,
        # Separate registry so the bundle never touches the user's normal GStreamer cache
        "GST_REGISTRY_1_0": os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"gst-registry-{key}.bin"),
    }
    still_missing = await _probe_elements(extra_env)
    if still_missing:
        decky.logger.warning(f"Bundle {key} loaded but still missing: {still_missing}")
        return still_missing, {}, f"Bundled plugins ({key}) did not provide everything."

    decky.logger.info(f"Using bundled GStreamer plugins: {key}")
    return [], extra_env, ""

# Get the PID of the actual GSR process rather than the flatpak command that spanwed it
async def _gsr_alive() -> bool:
    return await _exec("pgrep", "-f", GSR_PATTERN) == 0

def find_external_display():
    """Return the name of a connected non-internal connector (e.g. 'DP-1'), or None."""
    for status_file in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        connector = os.path.basename(os.path.dirname(status_file))  # e.g. card1-DP-1
        name = connector.split("-", 1)[1]                           # e.g. DP-1
        if name.startswith(("eDP", "LVDS", "DSI")):
            continue
        try:
            with open(status_file) as f:
                if f.read().strip() == "connected":
                    return name
        except OSError:
            continue
    return None

class Plugin:
    proc = None  # asyncio subprocess of the running stream, if any
    mode = None  # Gotta choose between GSR and GStreamer

    async def is_gsr_installed(self) -> bool:
        """True if the GPU Screen Recorder Flatpak is installed (user or system)."""
        # Decky's bundled Python can leak LD_LIBRARY_PATH etc. into child
        # processes and break system binaries, so give flatpak a clean env.
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": decky.DECKY_USER_HOME,
        }

        cmd = ["flatpak", "info", GSR_APP_ID]

        # If the backend is running as root, flatpak would only see system-wide
        # installs. Drop to the real user so user installs are visible too.
        if os.geteuid() == 0:
            cmd = ["runuser", "-u", decky.DECKY_USER, "--"] + cmd

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
        except Exception as e:
            decky.logger.error(f"Failed to run flatpak: {e}")
            return False

        installed = proc.returncode == 0
        decky.logger.info(f"GSR installed: {installed}")
        if not installed:
            decky.logger.info(f"flatpak info said: {stderr.decode().strip()}")
        return installed

    async def check_gstreamer(self) -> dict:
        missing, _, note = await _resolve_gst()
        if missing:
            decky.logger.warning(f"Missing GStreamer components: {missing}")
        return {"ok": not missing, "missing": missing, "note": note}

    async def get_capture_mode(self) -> dict:
        ext = find_external_display()
        gsr_ok = await self.is_gsr_installed()
        mode = "gsr" if (ext and gsr_ok) else "gstreamer"
        return {"mode": mode, "display": ext}

    async def get_selected_service(self) -> str:
        s = _load_state().get("service")
        return s if s in SERVICES else "twitch"

    async def set_selected_service(self, service: str) -> None:
        if service in SERVICES:
            _save_state(service=service)

    async def get_selected_quality(self) -> str:
        q = _load_state().get("quality")
        return q if q in QUALITY_PRESETS else DEFAULT_QUALITY

    async def set_selected_quality(self, quality: str) -> None:
        if quality in QUALITY_PRESETS:
            _save_state(quality=quality)


    async def stream_status(self) -> dict:
        running = self.proc is not None and self.proc.returncode is None
        return {"running": running, "pid": self.proc.pid if running else None}

    async def start_stream(self, service: str) -> dict:
        if self.proc is not None and self.proc.returncode is None:
            return {"ok": False, "error": "A stream is already running."}
        if service not in SERVICES:
            return {"ok": False, "error": f"Unknown service: {service}"}

        section = load_config()[service]
        if not section["ingest"] or not section["key"]:
            return {
                "ok": False,
                "error": f"Set the {service} stream key in "
                         f"{_config_path()}",
            }
        url = section["ingest"].rstrip("/") + "/" + section["key"]

        ext = find_external_display()
        use_gsr = bool(ext) and await self.is_gsr_installed()

        quality = _load_state().get("quality")
        bitrate = QUALITY_PRESETS.get(quality, QUALITY_PRESETS[DEFAULT_QUALITY])

        framerate = 30

        try:
            if use_gsr:
                cmd = _build_gsr_cmd(url, bitrate, framerate, ext)
                log_name = "gsr.log"
            else:
                cmd = _build_gst_cmd(url, bitrate, framerate)
                log_name = "gst.log"
        except Exception as e:
            decky.logger.exception("Failed to build stream command")
            return {"ok": False, "error": f"Internal error building command: {e}"}

        gst_env = {}
        if not use_gsr:
            missing, gst_env, note = await _resolve_gst()
            if missing:
                msg = "Missing GStreamer components: " + ", ".join(missing)
                if note:
                    msg += ". " + note
                return {"ok": False, "error": msg}

        env, user_kwargs = _user_ctx()
        env.update(gst_env)

        log_path = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, log_name)
        try:
            with open(log_path, "ab") as log:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                    **user_kwargs,
                )
        except Exception as e:
            decky.logger.error(f"Failed to launch stream: {e}")
            return {"ok": False, "error": f"Failed to launch: {e}"}

        self.mode = "gsr" if use_gsr else "gstreamer"

        # Catch immediate failures (bad args, missing plugin, etc.)
        await asyncio.sleep(2)
        if self.proc.returncode is not None:
            code = self.proc.returncode
            self.proc = None
            self.mode = None
            return {"ok": False, "error": f"Stream process exited immediately (code {code}). See {log_name}."}

        decky.logger.info(f"Stream started ({service}, {self.mode}), pid {self.proc.pid}")
        return {"ok": True, "pid": self.proc.pid}

    async def stop_stream(self) -> dict:
        proc = self.proc
        if proc is None:
            return {"ok": True}  # nothing of ours is running

        if self.mode == "gstreamer":
            if proc.returncode is None:
                proc.send_signal(signal.SIGINT)  # with -e this triggers a clean EOS shutdown
                try:
                    await asyncio.wait_for(proc.wait(), timeout=8)
                except asyncio.TimeoutError:
                    decky.logger.warning("gst-launch did not exit on SIGINT, killing")
                    proc.kill()
                    await proc.wait()
            self.proc = None
            self.mode = None
            decky.logger.info("Stream stopped")
            return {"ok": True}

        # ---- GSR path (unchanged from before) ----
        await _exec("pkill", "-INT", "-f", GSR_PATTERN)
        if proc.returncode is None:
            proc.send_signal(signal.SIGINT)

        for _ in range(40):
            if proc.returncode is not None and not await _gsr_alive():
                break
            await asyncio.sleep(0.2)
        else:
            decky.logger.warning("GSR did not exit on SIGINT, using flatpak kill")
            await _exec("flatpak", "kill", GSR_APP_ID)
            await asyncio.sleep(1)
            if proc.returncode is None:
                proc.kill()

        still_alive = await _gsr_alive()
        self.proc = None
        self.mode = None
        if still_alive:
            decky.logger.error("GSR still running after stop attempts")
            return {"ok": False, "error": "Could not stop GSR. Check gsr.log."}

        decky.logger.info("Stream stopped")
        return {"ok": True}

    async def _main(self):
        decky.logger.info("Decky Streamer loaded")

    async def _unload(self):
        # Don't leave a stream running if the plugin gets reloaded/unloaded.
        await self.stop_stream()

    async def _uninstall(self):
        pass