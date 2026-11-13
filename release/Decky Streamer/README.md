# Decky Streamer

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin to stream from your Steam Deck while you're in Game Mode.

Pick a service (Twitch, YouTube, or any custom RTMP endpoint), pick a quality, and hit **Start stream** — no need to leave Game Mode or fire up OBS.

## How it works

The plugin captures the screen and encodes in hardware, using one of two engines (chosen automatically):

- **GPU Screen Recorder (GSR)** — used when an external display is connected and GSR is installed. This is only an option when an external display is connected due to some real nasty driver-display quirks on the deck.
- **GStreamer + PipeWire** — the fallback, used in handheld mode or when GSR isn't installed. Captures the gamescope window over PipeWire, encodes H.264 with `vah264enc` (VA-API) and AAC with `avenc_aac`, and muxes FLV straight to your RTMP endpoint.

If your system (Steam OS) is missing any of the required GStreamer elements, the plugin falls back to bundled copies of `gst-plugin-va` and `gst-libav` (keyed to your GStreamer/FFmpeg version), loaded with an isolated plugin registry so they don't touch the rest of your system. Bazzite has all of the components GStreamer needs to stream, so it should work at all times on Bazzite.

The bundled elements are tested against Steam OS >TODO I FORGOR TO CHECK THE VERSION<

## Requirements

- [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- *(Optional, for docked/external display use)* [GPU Screen Recorder](https://flathub.org/en/apps/com.dec05eba.gpu_screen_recorder) from Flathub

## Installation

1. Enable **Dev mode** in Decky Loader (Plugin Manager).
2. Hit **Install from GitHub** and paste:
   `https://github.com/famellad/decky-streamer/releases/download/0.1.1/decky-streamer-v0.1.1.zip`

*(Or build a release zip yourself — see [Building](#building) — and install it with Decky's usual zip installer.)*

## Setup

### Stream keys

Upon first use, the plugin will generate a config file in your homebrew directory, you need to add the stream keys of the services you want to use in order to stream, go to desktop mode and edit that file (you can do it from game mode with SSH if you know how to, but it's beyond the scope of this README):

`~/homebrew/settings/Decky Streamer/config.json`

```json
{
  "twitch":  { "ingest": "rtmp://live.twitch.tv/app",      "key": "your-twitch-key" },
  "youtube": { "ingest": "rtmp://a.rtmp.youtube.com/live2", "key": "your-youtube-key" },
  "custom":  { "ingest": "rtmp://your-server.example/live", "key": "whatever" }
}
```

The file is owned by your user and not world-readable, since it holds stream keys.

### GPU Screen Recorder (if you're using the deck docked)

## DISREGARD IF YOU'RE USING STEAM OS

If you plan to stream with an external display attached, install GSR in desktop mode:

```sh
flatpak install flathub com.dec05eba.gpu_screen_recorder
```

The plugin detects it automatically and prefers it whenever an external display is connected; handheld mode (or a missing GSR install) just falls back to GStreamer.

## Usage

1. Open the **Decky Loader** side panel.
2. Navigate to **Decky Streamer** and open it.
3. Pick a service and a quality.
4. Hit **Start stream** — the status line confirms you're streaming (with the encoder process PID should your nerd ass ever need it).
5. **Stop stream** when you're done.

Quality presets (video bitrate):

| Potato | Low | Balanced *(default)* | High | Very High |
| --- | --- | --- | --- | --- |
| 1 Mbps | 2.2 Mbps | 4.5 Mbps | 6.5 Mbps | 8 Mbps |

I plan to add support for other framerates if y'all behave.

### Note on performance

I haven't properly benchmarked this in practice yet. If you stream with it, real-world feedback (and reports of which engine you got) is very welcome.
However, preliminary testing shows the performance loss of using GPU Screen Recorder is negligible, as expected, and it's between 2-4% while using GStreamer, so you should be good.

### Note on the logs

The plugin's log folder (`~/homebrew/logs/Decky Streamer/`) contains `gsr.log` (for GPU Screen Recorder) and `gst.log` (for GStreamer). It also has a dated log file for other things. **These may contain your stream key** — check before posting logs in an issue or on a forum.

## Building

You'll need Node.js and [pnpm](https://pnpm.io).

```sh
./package.sh
```

That's it — the script fetches the bundled GStreamer plugins (see `gst-plugins.manifest`), installs dependencies, builds the frontend, and zips a ready-to-install release into `release/`. The `.vscode/` folder is just local editor/dev config that I have mangled beyond recognition because I was in a hurry (?); ignore it.

## AI Disclaimer

The TypeScript portion (and a couple of Python helper functions) were written with the help of an AI assistant; every line of code was human-reviewed. You are free to send a hitman to my place to shoot me in the back of the head — I don't speak TypeScript, sue me.

## License

BSD 3-Clause — see [LICENSE](LICENSE).

Yes I know I gotta update the license too gimme a break.
