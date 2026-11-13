#!/usr/bin/env bash
set -euo pipefail

NAME="Decky Streamer"                      # must match plugin.json "name"
VERSION=$(node -p "require('./package.json').version")
ZIP="decky-streamer-v${VERSION}.zip"

# --- License compliance: don't package without the notices ---
for f in THIRD_PARTY_NOTICES.md licenses/LGPL-2.1.txt; do
  [ -f "$f" ] || { echo "Missing $f (see THIRD_PARTY_NOTICES.md instructions)" >&2; exit 1; }
done

bash fetch-gst-plugins.sh

# Every bundled package+version must appear in the notices, written as "<package> <version>"
while read -r key pkg ver sha; do
  [[ -z "${key:-}" || "$key" == \#* ]] && continue
  grep -qF "$pkg $ver" THIRD_PARTY_NOTICES.md || {
    echo "THIRD_PARTY_NOTICES.md does not mention '$pkg $ver' (update it to match gst-plugins.manifest)" >&2
    exit 1
  }
done < gst-plugins.manifest

echo "Cleaning up..."
sudo rm -rf node_modules

pnpm i --frozen-lockfile
pnpm run build

rm -rf release && mkdir -p "release/$NAME"
cp -r dist main.py plugin.json package.json README.md LICENSE \
      THIRD_PARTY_NOTICES.md licenses gst-plugins "release/$NAME/"
[ -d defaults ] && cp -r defaults "release/$NAME/"

(cd release && zip -r "$ZIP" "$NAME")
echo "Built release/$ZIP"