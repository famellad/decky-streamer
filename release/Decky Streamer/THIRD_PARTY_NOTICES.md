# Third-party notices

Decky Streamer itself is licensed as described in `LICENSE`. This release also
includes the following third-party components, which are separate works under
their own licenses.

## Bundled GStreamer plugins

| Package (Arch Linux) | Upstream project | Provides | License |
|---|---|---|---|
| gst-plugin-va 1.28.9-1 | GStreamer gst-plugins-bad 1.28.9 (the `va` plugin, `libgstva.so`) | `vapostproc`, `vah264enc` | LGPL-2.1-or-later |
| gst-libav 1.28.4-3 | GStreamer gst-libav 1.28.4 (`libgstlibav.so`) | `avenc_aac` | LGPL-2.1-or-later |

These are the unmodified plugin binaries from the Arch Linux packages, taken
from the Arch Linux Archive (https://archive.archlinux.org/packages/). The exact
package versions and their SHA-256 checksums are listed in `gst-plugins.manifest`,
and the files are placed under `gst-plugins/`.

`libgstlibav.so` links dynamically against the FFmpeg libraries already
installed on the user's system. FFmpeg itself is not included in this release.

### When they are used

Decky Streamer only loads these plugins if the system's own GStreamer is
missing the elements it needs (for example on stock SteamOS). If the system
already provides them, the bundled copies are ignored. To stop using them, or
to use your own build instead, delete or replace the files in `gst-plugins/`.
They are loaded as ordinary GStreamer plugins through `GST_PLUGIN_PATH`.

### Source code

The source for the exact versions above is available from:

- GStreamer release tarballs: https://gstreamer.freedesktop.org/src/
  (gst-plugins-bad 1.28.9 and gst-libav 1.28.4)
- Arch Linux packaging for `gst-plugin-va` and `gst-libav`:
  https://gitlab.archlinux.org/archlinux/packaging/packages

If you cannot get the source from those locations, open an issue at
<REPO URL> and it will be provided.

### License text

The full text of the GNU Lesser General Public License, version 2.1, is in
`licenses/LGPL-2.1.txt`. License files extracted from the Arch packages, where
they provide any, are in `gst-plugins/<version>/licenses/`.

## Patents

H.264 and AAC are formats that may be covered by patents in some countries.
Nothing in this project or these notices grants any patent license.
