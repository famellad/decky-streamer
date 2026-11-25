import pwd
import asyncio
import glob
import os
import re
import shutil

import decky

# -----------------------------------------
# *   *         *                            
# *   *   ***   *  ****    ***    **   ****  
# *****  *   *  *  *   *  *   *  *    *      
# *   *  *****  *  *   *  *****  *     ***   
# *   *  *      *  ****   *      *        *  
# *   *   ***   *  *       ***   *    ****   
#                  *                         
# -----------------------------------------

def log_path(mode: str) -> str:
    return os.path.join(decky.DECKY_PLUGIN_LOG_DIR, mode)

# Check whether we are running as root
# This small function is here because I refuse to import os in main.py just for two calls
# YES I KNOW SIGNAL IS ALSO IMPORTED THERE FOR ONLY TWO CALLS YOU DON'T NEED TO TELL ME
def are_we_root():
    return os.geteuid() == 0

# Make an environment for the REAL user to run the processes, can't assume the user is "deck" because of Bazzite
def user_env() -> dict: # was _user_env
    """Environment for child processes, as the real (non-root) user."""
    pw = pwd.getpwnam(decky.DECKY_USER)
    runtime_dir = f"/run/user/{pw.pw_uid}"
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": pw.pw_dir,
        "XDG_RUNTIME_DIR": runtime_dir,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        "WAYLAND_DISPLAY": "gamescope-0",  # name of the Wayland socket in Game Mode
    }

# Run an async command as the user, discard stdout and stderr because we're heathens
async def exec_cmd(*cmd, extra_env=None) -> int: # was _exec
    env = user_env()
    if extra_env:
        env.update(extra_env)
    p = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await p.wait()
    return p.returncode

async def capture(*cmd) -> str: # was _capture
    env = user_env()
    p = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await p.communicate()
    return out.decode(errors="replace")

def find_external_display():
    """Return the name of a connected non-internal connector (e.g. 'DP-1'), or None."""
    for status_file in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        connector = os.path.basename(os.path.dirname(status_file))  # card1-DP-1
        name = connector.split("-", 1)[1]                           # DP-1
        if name.startswith(("eDP", "LVDS", "DSI")):
            continue
        try:
            with open(status_file) as f:
                if f.read().strip() == "connected":
                    return name
        except OSError:
            continue
    return None

# -------------------
#  ***    ****  ****   
# *   *  *      *   *  
# *       ***   ****   
# *  **      *  * *    
# *   *      *  *  *   
#  ****  ****   *   *  
# -------------------

GSR_APP_ID = "com.dec05eba.gpu_screen_recorder"
GSR_PATTERN = "gpu-screen-recorder -w"   # was "... -w screen", and it would have been the end of it and super easy and not a hassle at all, now we have to pass a connector name because the Steam Deck AMD drivers are fucking stupid

# GPU Screen Recorder (Flatpak) command builder
def build_gsr_cmd(url: str, bitrate: int, framerate: int, ext: str) -> list:
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

# Get whether GSR is running
async def gsr_alive() -> bool:
    return await exec_cmd("pgrep", "-f", GSR_PATTERN) == 0

# -------------------------------------------------------
#  ***    ****   *                                         
# *   *  *       *    **   ***    ***    * *    ***    **  
# *       ***   ***  *    *   *      *  * * *  *   *  *    
# *  **      *   *   *    *****   ****  * * *  *****  *    
# *   *      *   *   *    *      *   *  * * *  *      *    
#  ****  ****    **  *     ***    ****  * * *   ***   *    
# -------------------------------------------------------

# Every element the pipeline in _build_gst_cmd uses (queue is core, so it's not listed).
GST_REQUIRED = (
    "pipewiresrc", "pulsesrc",
    "vapostproc", "vah264enc", "h264parse",
    "audioconvert", "audioresample", "avenc_aac", "aacparse",
    "flvmux", "rtmp2sink",
)

# GStreamer command builders
#   - Encoder Line
def _gst_video_encode(bitrate: int, framerate: int) -> list:
    return [
        "vapostproc", "!",
        "vah264enc", f"bitrate={bitrate}", f"key-int-max={framerate}", "!",
        "h264parse",
    ]

#   - Rest of it
def build_gst_cmd(url: str, bitrate: int, framerate: int) -> list:
    return [
        "gst-launch-1.0", "-e",
        "flvmux", "name=mux", "streamable=true", "!",
        "rtmp2sink", f"location={url}",
        "pipewiresrc", "target-object=gamescope", "do-timestamp=true", f"keepalive-time={round(1000 / framerate)}", "!", "queue", "!", # Keepalive matches frametime
        *_gst_video_encode(bitrate, framerate), "!", "queue", "!", "mux.",
        "pulsesrc", "device=@DEFAULT_MONITOR@", "!", "queue", "!",
        "audioconvert", "!", "audioresample", "!",
        "avenc_aac", "bitrate=128000", "!", "aacparse", "!", "queue", "!", "mux.",
    ]

# Check to see which GStreamer elements the system has, Bazzite has everything necessary, SteamOS is missing a few
async def _probe_elements(extra_env=None) -> list:
    """Names from GST_REQUIRED that gst-inspect cannot find."""
    # First check alone: with a fresh registry it scans every plugin once,
    # and the parallel checks after it reuse the result.
    first = await exec_cmd("gst-inspect-1.0", "--exists", GST_REQUIRED[0], extra_env=extra_env)
    rest = await asyncio.gather(
        *(exec_cmd("gst-inspect-1.0", "--exists", e, extra_env=extra_env)
          for e in GST_REQUIRED[1:])
    )
    return [e for e, rc in zip(GST_REQUIRED, [first, *rest]) if rc != 0]

# Figure out the exact directory name so we can use ffmpeg
async def _bundle_key():
    """Compatibility key like '1.28-ffmpeg62', or None if it can't be worked out."""
    # What does GStreamer say?
    out = await capture("gst-inspect-1.0", "--version")
    m = re.search(r"GStreamer (\d+\.\d+)", out)

    if not m:
        return None
    
    # Make sure we grab the soname with the highest number to avoid weird versioning issues in freak systems with multiple installs
    av = None
    for d in ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu"):
        found = []
        for p in glob.glob(os.path.join(d, "libavcodec.so.*")):
            mm = re.search(r"libavcodec\.so\.(\d+)", os.path.basename(p))
            if mm:
                found.append(int(mm.group(1)))
        if found:
            av = max(found)
            break
    
    # If we couldn't find any, something's wrong
    if av is None:
        return None
    
    return f"{m.group(1)}-ffmpeg{av}"

async def _resolve_gst():#
    """Decide how GStreamer can be used. Returns (missing, extra_env, note)."""
    path = user_env()["PATH"]

    # Return immediately if we can't even probe GStreamer
    no_tools = [
        t for t in ("gst-launch-1.0", "gst-inspect-1.0")
        if shutil.which(t, path=path) is None
    ]
    if no_tools:
        return no_tools, {}, ""

    missing = await _probe_elements()
    if not missing:
        return [], {}, ""  # the system has everything: the bundle stays unused and we keep chugging along

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

    # Check whether we're still missing anything, despite using the bundled plugins
    still_missing = await _probe_elements(extra_env)
    if still_missing:
        decky.logger.warning(f"Bundle {key} loaded but still missing: {still_missing}")
        return still_missing, {}, f"Bundled plugins ({key}) did not provide everything."

    decky.logger.info(f"Using bundled GStreamer plugins: {key}")
    return [], extra_env, ""
