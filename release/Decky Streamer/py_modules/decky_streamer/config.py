"""Settings for Decky Streamer: services, quality presets, config.json, state.json."""
import json
import os

import decky

SERVICES = ("twitch", "youtube", "custom")
DEFAULT_SERVICE = "twitch"

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

DEFAULT_FRAMERATE = 60


# ---------- paths ----------

def config_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "config.json")

def _state_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "state.json")


# ---------- state.json: what the user picked in the panel ----------

# Da state machine (file, my lawyer tells me I shouldn't call it a state machine because there's a very strict definition of what a state machine is and I'm gonna look like a fool)
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

def get_service() -> str:
    s = _load_state().get("service")
    return s if s in SERVICES else DEFAULT_SERVICE

def set_service(service: str) -> None:
    if service in SERVICES:
        _save_state(service=service)

def get_quality() -> str:
    q = _load_state().get("quality")
    return q if q in QUALITY_PRESETS else DEFAULT_QUALITY

def set_quality(quality: str) -> None:
    if quality in QUALITY_PRESETS:
        _save_state(quality=quality)

def get_bitrate() -> int:
    """Video bitrate in kbit/s for the selected quality."""
    return QUALITY_PRESETS[get_quality()]


# ---------- config.json: ingest addresses and stream keys, edited by the user ----------
# TODO make a way to edit this from within the plugin itself, even if it means using the godawful screen keyboard

def _write_default_config():
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    path = config_path()
    with open(path, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    os.chmod(path, 0o600)   # contains stream keys

def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = config_path()

    # If a default config doesn't exist, make it.
    if not os.path.exists(path):
        _write_default_config()
        return cfg

    # Restore permissions in case an editor messed with them
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        decky.logger.warning(f"Could not tighten permissions on config: {e}")

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