#!/usr/bin/env bash
# Fetch the BambuStudio source tree at the given tag.
#
# Uses the codeload tarball rather than git clone: the source tree is ~540 MB
# and only a handful of files ever need to be inspected, so a full history is
# pure overhead. The tarball is also far more reliable behind CI's network.
set -euo pipefail

VERSION="${1:-v02.09.01.70}"
DEST="${BSW_SRC:-$(pwd)/BambuStudio}"

if [ -f "${DEST}/src/libslic3r/CMakeLists.txt" ]; then
  echo "[fetch] source already present at $DEST — skipping"
  exit 0
fi

echo "[fetch] BambuStudio $VERSION -> $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"

# codeload serves the tag without the leading "v" in the archive name.
STRIPPED="${VERSION#v}"
URL="https://codeload.github.com/bambulab/BambuStudio/tar.gz/refs/tags/$VERSION"

echo "[fetch] downloading $URL"
curl -fsSL --retry 5 --retry-delay 5 --max-time 1800 -o /tmp/bambu.tar.gz "$URL"

echo "[fetch] extracting"
tar xzf /tmp/bambu.tar.gz -C /tmp
rm -f /tmp/bambu.tar.gz

# The archive extracts to BambuStudio-<version>
SRC_DIR="$(find /tmp -maxdepth 1 -type d -name "BambuStudio-*" | head -1)"
if [ -z "$SRC_DIR" ]; then
  echo "[fetch] ERROR: extracted directory not found" >&2
  exit 1
fi

mv "$SRC_DIR" "$DEST"

test -f "${DEST}/src/libslic3r/CMakeLists.txt" || {
  echo "[fetch] ERROR: source tree incomplete" >&2
  exit 1
}

echo "[fetch] done: $(du -sh "$DEST" | cut -f1)"
