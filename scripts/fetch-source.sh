#!/usr/bin/env bash
# Fetch the BambuStudio source tree at the given tag.
#
# Uses the codeload tarball rather than git clone: the tree is ~540 MB and
# only a handful of files are ever inspected, so a full history is pure
# overhead. The tarball is also far more reliable behind CI's network.
set -euo pipefail

VERSION="${1:-v02.09.01.70}"
DEST="${BSW_SRC:-$(pwd)/BambuStudio}"

if [ -f "${DEST}/src/libslic3r/CMakeLists.txt" ]; then
  echo "[fetch] source already present at $DEST -- skipping"
  exit 0
fi

echo "[fetch] BambuStudio $VERSION -> $DEST"
rm -rf "$DEST"

URL="https://codeload.github.com/bambulab/BambuStudio/tar.gz/refs/tags/${VERSION}"
echo "[fetch] downloading $URL"
curl -fsSL --retry 5 --retry-delay 5 --max-time 1800 -o /tmp/bambu.tar.gz "$URL"

TMPEXTRACT=$(mktemp -d)
echo "[fetch] extracting to $TMPEXTRACT"
tar xzf /tmp/bambu.tar.gz -C "$TMPEXTRACT"
rm -f /tmp/bambu.tar.gz

SRC_DIR=$(find "$TMPEXTRACT" -maxdepth 1 -mindepth 1 -type d | head -1)
if [ -z "$SRC_DIR" ]; then
  echo "[fetch] ERROR: extracted directory not found" >&2
  exit 1
fi

# mv into a *non-existent* path so it renames rather than nesting.
# `mkdir -p $DEST` followed by `mv $SRC $DEST` would produce
# $DEST/BambuStudio-<ver>/src/..., and the completeness check below would
# fail with a misleading 'source tree incomplete'.
mv "$SRC_DIR" "$DEST"
rmdir "$TMPEXTRACT" 2>/dev/null || true

test -f "${DEST}/src/libslic3r/CMakeLists.txt" || {
  echo "[fetch] ERROR: source tree incomplete" >&2
  exit 1
}

echo "[fetch] done: $(du -sh "$DEST" | cut -f1)"
