#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

MANIFEST=gst-plugins.manifest
OUT=gst-plugins
BASE=https://archive.archlinux.org/packages

rm -rf "$OUT"; mkdir -p "$OUT" .cache

while read -r key pkg ver sha; do
  [[ -z "${key:-}" || "$key" == \#* ]] && continue
  file="$pkg-$ver-x86_64.pkg.tar.zst"
  url="$BASE/${pkg:0:1}/$pkg/$file"

  [ -f ".cache/$file" ] || curl -fL "$url" -o ".cache/$file"
  actual=$(sha256sum ".cache/$file" | cut -d' ' -f1)
  if [ "$sha" = "TODO" ]; then
    echo "$file sha256 = $actual"
  elif [ "$sha" != "$actual" ]; then
    echo "CHECKSUM MISMATCH for $file" >&2; exit 1
  fi

  mkdir -p "$OUT/$key/licenses"
  tar -I zstd -xf ".cache/$file" -C "$OUT/$key" --strip-components=3 \
      --wildcards 'usr/lib/gstreamer-1.0/*.so'
  tar -I zstd -xf ".cache/$file" -C "$OUT/$key/licenses" --strip-components=3 \
      --wildcards 'usr/share/licenses/*' 2>/dev/null || true
done < "$MANIFEST"

echo "Bundle contents:"; find "$OUT" -name '*.so'
