import asyncio
import json
import os
import pwd
import signal

import decky

GSR_APP_ID = "com.dec05eba.gpu_screen_recorder"
GSR_PATTERN = "gpu-screen-recorder -w screen"
SERVICES = ("twitch", "youtube", "custom")

DEFAULT_CONFIG = {
    "twitch":  {"ingest": "rtmp://live.twitch.tv/app",        "key": ""},
    "youtube": {"ingest": "rtmp://a.rtmp.youtube.com/live2",  "key": ""},
    "custom":  {"ingest": "",                                  "key": ""},
}


# ---------- config ----------

def _config_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "config.json")

def _write_default_config():
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    path = _config_path()
    with open(path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    # Contains stream keys: owned by the user, not world-readable.
    pw = pwd.getpwnam(decky.DECKY_USER)
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

def _state_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "state.json")

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

async def _exec(*cmd) -> int:
    env, user_kwargs = _user_ctx()
    p = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        **user_kwargs,
    )
    await p.wait()
    return p.returncode

# Get the PID of the actual GSR process rather than the flatpak command that spanwed it
async def _gsr_alive() -> bool:
    return await _exec("pgrep", "-f", GSR_PATTERN) == 0

class Plugin:
    proc = None  # asyncio subprocess of the running stream, if any

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

    async def get_selected_service(self) -> str:
        try:
            with open(_state_path()) as f:
                s = json.load(f).get("service")
            decky.logger.info(f"get_selected_service -> {s}")
            return s if s in SERVICES else "twitch"
        except Exception as e:
            decky.logger.error(f"get_selected_service failed: {e}")
            return "twitch"

    async def set_selected_service(self, service: str) -> None:
        decky.logger.info(f"set_selected_service({service})")
        if service not in SERVICES:
            return
        try:
            os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
            with open(_state_path(), "w") as f:
                json.dump({"service": service}, f)
        except Exception as e:
            decky.logger.error(f"set_selected_service failed: {e}")


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
                "error": f"Set the {service} ingest address and stream key in "
                         f"{_config_path()}",
            }
        url = section["ingest"].rstrip("/") + "/" + section["key"]

        cmd = [
            "flatpak", "run", "--command=gpu-screen-recorder", GSR_APP_ID,
            "-w", "screen",
            "-f", "30",
            "-a", "default_output",
            "-c", "flv",
            "-o", url,
        ]

        env, user_kwargs = _user_ctx()
        log_path = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "gsr.log")
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
            decky.logger.error(f"Failed to launch GSR: {e}")
            return {"ok": False, "error": f"Failed to launch: {e}"}

        # Catch immediate failures (bad args, capture permission, etc.)
        await asyncio.sleep(2)
        if self.proc.returncode is not None:
            code = self.proc.returncode
            self.proc = None
            return {"ok": False, "error": f"GSR exited immediately (code {code}). See gsr.log."}

        decky.logger.info(f"Stream started ({service}), pid {self.proc.pid}")
        return {"ok": True, "pid": self.proc.pid}

    async def stop_stream(self) -> dict:
        proc = self.proc
        # 1. Graceful: SIGINT the real GSR process inside the sandbox,
        #    and the flatpak wrapper too.
        await _exec("pkill", "-INT", "-f", GSR_PATTERN)
        if proc is not None and proc.returncode is None:
            proc.send_signal(signal.SIGINT)

        # 2. Wait up to ~8s for everything to actually exit.
        for _ in range(40):
            wrapper_gone = proc is None or proc.returncode is not None
            if wrapper_gone and not await _gsr_alive():
                break
            await asyncio.sleep(0.2)
        else:
            # 3. Forceful fallback: kill the whole sandbox.
            decky.logger.warning("GSR did not exit on SIGINT, using flatpak kill")
            await _exec("flatpak", "kill", GSR_APP_ID)
            await asyncio.sleep(1)
            if proc is not None and proc.returncode is None:
                proc.kill()

        still_alive = await _gsr_alive()
        self.proc = None
        if still_alive:
            decky.logger.error("GSR still running after stop attempts")
            return {"ok": False, "error": "Could not stop GSR. Check gsr.log."}

        decky.logger.info("Stream stopped")
        return {"ok": True}

    async def _main(self):
        decky.logger.info("Decky GSR loaded")

    async def _unload(self):
        # Don't leave a stream running if the plugin gets reloaded/unloaded.
        await self.stop_stream()

    async def _uninstall(self):
        pass