#!/usr/bin/env bash
set -euo pipefail

NAME="Decky Streamer"                      # must match plugin.json "name"
VERSION=$(node -p "require('./package.json').version")
ZIP="decky-streamer-v${VERSION}.zip"

bash fetch-gst-plugins.sh

echo "Cleaning up..."
sudo rm -rf node_modules

pnpm i --frozen-lockfile
pnpm run build

rm -rf release && mkdir -p "release/$NAME"
cp -r dist main.py plugin.json package.json README.md LICENSE "release/$NAME/"
[ -d gst-plugins ] && cp -r gst-plugins "release/$NAME/"
[ -d defaults ] && cp -r defaults "release/$NAME/"

(cd release && zip -r "$ZIP" "$NAME")
echo "Built release/$ZIP"