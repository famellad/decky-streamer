import asyncio
import os

import decky

GSR_APP_ID = "com.dec05eba.gpu_screen_recorder"

class Plugin:
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

    async def _main(self):
        decky.logger.info("Decky GSR loaded")

    async def _unload(self):
        decky.logger.info("Decky GSR unloading")

    async def _uninstall(self):
        decky.logger.info("Decky GSR uninstalled")