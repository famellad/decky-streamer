import asyncio
import signal

import decky
from decky_streamer import config
from decky_streamer import system

class Plugin:
    proc = None  # asyncio subprocess of the running stream, if any
    mode = None  # Gotta choose between GSR and GStreamer, so we know what's going on later
    lock = asyncio.Lock() # Serialize the start loop to prevent double-start races

    # Check whether Flatpak GSR is a thing in the user's system
    async def is_gsr_installed(self) -> bool:
        """True if the GPU Screen Recorder Flatpak is installed (user or system)."""
        # Decky's bundled Python can leak LD_LIBRARY_PATH etc. into child
        # processes and break system binaries, so give flatpak a clean env.
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": decky.DECKY_USER_HOME,
        }

        cmd = ["flatpak", "info", system.GSR_APP_ID]

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

    # Check whether GStreamer is a thing, and what elements are missing if any
    async def check_gstreamer(self) -> dict:
        missing, _, note = await system.resolve_gst()
        if missing:
            decky.logger.warning(f"Missing GStreamer components: {missing}")
        return {"ok": not missing, "missing": missing, "note": note}

    # Determine which capture mode is gonna get chosen, always falls back to GStreamer if the system doesn't meet the special requirements for GSR to work
    async def get_capture_mode(self) -> dict:
        ext = system.find_external_display()
        gsr_ok = await self.is_gsr_installed()
        mode = "gsr" if (ext and gsr_ok) else "gstreamer"
        return {"mode": mode, "display": ext, "gsr_installed": gsr_ok}

    # Where we droppin'? (Defaults to Twich because that's what all the hip kids are using ig)
    async def get_selected_service(self) -> str:
        return config.get_service()

    # Change the service
    async def set_selected_service(self, service: str) -> None:
        config.set_service(service)

    # How good we droppin'?
    async def get_selected_quality(self) -> str:
        return config.get_quality()

    # Change the quality
    async def set_selected_quality(self, quality: str) -> None:
        config.set_quality(quality)

    # Check whether the stream is running
    async def stream_status(self) -> dict:
        running = self.proc is not None and self.proc.returncode is None
        return {"running": running, "pid": self.proc.pid if running else None}

    # Async lock wrappers
    async def start_stream(self, service: str) -> dict:
        async with self.lock:
            return await self._start_stream(service)

    async def stop_stream(self) -> dict:
        async with self.lock:
            return await self._stop_stream()

    # JUST GO FOR IT MAN START THE DAMN STREAM ALREADY
    async def _start_stream(self, service: str) -> dict:
        # ... Unless it's already running, obviously
        if self.proc is not None and self.proc.returncode is None:
            return {"ok": False, "error": "A stream is already running."}
        # ... Or the user fucked something up inside state.json, a file they shouldn't have touched to begin with
        if service not in config.SERVICES:
            return {"ok": False, "error": f"Unknown service: {service}. Select something from the service dropdown."}
        # ... Or we're root, no monkey business I say
        if system.are_we_root():
            return {"ok": False, "error": "Decky Streamer must not run as root. Remove the \"root\" flag from plugin.json."}


        # Figure out where to stream
        section = config.load_config()[service]
        if not section["ingest"] or not section["key"]:
            return {
                "ok": False,
                "error": f"Set the {service} stream key in "
                         f"{config.config_path()}",
            }
        url = section["ingest"].rstrip("/") + "/" + section["key"]

        ext = system.find_external_display()
        use_gsr = bool(ext) and await self.is_gsr_installed() # Check whether: 1. There's an external display AND 2. GSR is installed, THEN we can stream...
        # TODO Currently Steam OS cannot stream with GSR even with an external display, but I bet the solution is really fucking stupid I just have to look into the logs

        bitrate = config.get_bitrate()
        framerate = config.DEFAULT_FRAMERATE

        # Figure out how to stream
        try:
            if use_gsr:
                cmd = system.build_gsr_cmd(url, bitrate, framerate, ext)
            else:
                cmd = system.build_gst_cmd(url, bitrate, framerate)
        except Exception as e: # If we reach this exception something really went horribly fucking wrong tbh
            decky.logger.exception("Failed to build stream command")
            return {"ok": False, "error": f"Internal error building command: {e}"}

        # If we fall back to GStreamer, we check whether we have all the elements we need
        gst_env = {}
        if not use_gsr:
            missing, gst_env, note = await system.resolve_gst()
            if missing:
                msg = "Missing GStreamer components: " + ", ".join(missing)
                if note:
                    msg += ". " + note
                return {"ok": False, "error": msg}

        # Get the user context, make it GStreamer friendly
        env = system.user_env()
        env.update(gst_env)

        # Finally, after we've learned everything we can in this program, launch the stream with the set parameters, in the set mode, for the set system, with the set user
        try:
            with open(system.log_path(self.mode), "wb") as log:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        except Exception as e: # Or not ig
            decky.logger.error(f"Failed to launch stream: {e}")
            return {"ok": False, "error": f"Failed to launch: {e}"}

        self.mode = "gsr" if use_gsr else "gstreamer"

        # Catch immediate failures (bad args, missing plugin, etc.)
        await asyncio.sleep(2)
        if self.proc.returncode is not None:
            code = self.proc.returncode
            tmp_mode = self.mode
            self.proc = None
            self.mode = None
            return {"ok": False, "error": f"Stream process exited immediately (code {code}). See the {tmp_mode}.log file in {decky.DECKY_PLUGIN_LOG_DIR}."}

        decky.logger.info(f"Stream started ({service}, {self.mode}), pid {self.proc.pid}")
        return {"ok": True, "pid": self.proc.pid}

    async def _stop_stream(self) -> dict:
        proc = self.proc
        if proc is None:
            return {"ok": True}  # nothing of ours is running, so what are we even doing

        # Stop GStreamer if that's what we're using
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

        # GSR path, so stop it
        await system.exec_cmd("pkill", "-INT", "-f", system.GSR_PATTERN)
        if proc.returncode is None:
            proc.send_signal(signal.SIGINT)

        
        for _ in range(40):
            if proc.returncode is not None and not await system.gsr_alive():
                break
            await asyncio.sleep(0.2)
        else: # ... Or kill it if it's being stubborn
            decky.logger.warning("GSR did not exit on SIGINT, using flatpak kill")
            await system.exec_cmd("flatpak", "kill", system.GSR_APP_ID)
            await asyncio.sleep(1)
            if proc.returncode is None:
                proc.kill()

        # This is the part where we start freaking out
        # TODO maybe tell the user they should restart their deck?
        # TODO actually, what happens with the state if we have a stream running and just... Reboot the Deck?...
        still_alive = await system.gsr_alive()
        self.proc = None
        self.mode = None
        if still_alive:
            decky.logger.error("GSR still running after stop attempts")
            return {"ok": False, "error": "Could not stop GSR. Check gsr.log."}

        decky.logger.info("Stream stopped")
        return {"ok": True}

    async def _main(self):
        decky.logger.info("Decky Streamer loaded")

        # Make sure the plugin is running as a regular user, we don't want no monkey business here
        if system.are_we_root:
            return {"ok": False, "error": "Decky Streamer must not run as root. Remove the \"root\" flag from plugin.json."}

    async def _unload(self):
        # Don't leave a stream running if the plugin gets reloaded/unloaded.
        await self.stop_stream()

    async def _uninstall(self):
        pass