#!/usr/bin/env bash
# Provide the zlib and libpng libslic3r expects, via Emscripten's ports.
#
# Emscripten ships both as first-class ports (USE_ZLIB / USE_LIBPNG). Letting
# emcc build them beats a manual cross-compile here:
#   - the sysroot copy is already compiled with the same -pthread and
#     -fwasm-exceptions flags the final link uses, so no ABI surprises;
#   - nothing to cache, checksum or pin.
#
# libslic3r wants them through find_package, and emsdk installs no CMake config
# for ports, so this script asks embuilder to populate the sysroot and then
# synthesises the two config directories FindZLIB / FindPNG will accept.
set -euo pipefail

PREFIX="${DEPS_INSTALL:-$(pwd)/deps-install}"
EM_PREFIX="${EMSDK:-/opt/emsdk}/upstream/emscripten"
SYSROOT="${EM_PREFIX}/cache/sysroot"

# The port objects must carry the same threading feature set as the main
# build. Without -pthread their objects lack the atomics/bulk-memory target
# features and wasm-ld rejects the link:
#   --shared-memory is disallowed by png.c.o because it was not compiled with
#   'atomics' or 'bulk-memory' features.
# embuilder cannot produce atomics-enabled ports: verified with ar + strings on
# its libpng.a, which contains no "atomics"/"bulk-memory" target feature. It
# builds ports with a fixed internal configuration and ignores both CFLAGS and
# EMCC_CFLAGS for the target features.
#
# The main module is a shared-memory pthread module, and wasm-ld refuses to mix
# non-atomics objects into one. So the libraries are compiled here, directly
# from source, with the same flags the link uses.
echo "[zlibpng] building zlib and libpng from source (threads enabled)"
PORT_SRC=/tmp/port-src
rm -rf "$PORT_SRC"; mkdir -p "$PORT_SRC"

for spec in "zlib:https://github.com/madler/zlib/archive/refs/tags/v1.2.13.tar.gz" \
            "libpng:https://github.com/pnggroup/libpng/archive/refs/tags/v1.6.39.tar.gz"; do
  name="${spec%%:*}"
  url="${spec#*:}"
  echo "[zlibpng] fetching $name"
  curl -fsSL "$url" | tar xz -C "$PORT_SRC"
done

# zlib
ZLIB_DIR="$(find "$PORT_SRC" -maxdepth 1 -type d -name 'zlib-*' | head -1)"
( cd "$ZLIB_DIR" && \
  emcc -O2 -pthread -sSUPPORT_LONGJMP=wasm -DHAVE_UNISTD_H \
       -c adler32.c compress.c crc32.c deflate.c gzclose.c gzlib.c gzread.c \
          gzwrite.c infback.c inffast.c inflate.c inftrees.c trees.c uncompr.c \
          zutil.c && \
  emar rcs "$PREFIX/lib/libz.a" ./*.o )

# libpng
PNG_DIR="$(find "$PORT_SRC" -maxdepth 1 -type d -name 'libpng-*' | head -1)"
( cd "$PNG_DIR" && \
  emcc -O2 -pthread -sSUPPORT_LONGJMP=wasm \
       -DPNG_NO_READ_tIME -I"$ZLIB_DIR" \
       -c png.c pngerror.c pngget.c pngmem.c pngpread.c pngread.c \
          pngrio.c pngrtran.c pngrutil.c pngset.c pngtrans.c pngwio.c \
          pngwrite.c pngwtran.c pngwutil.c && \
  emar rcs "$PREFIX/lib/libpng.a" ./*.o )

echo "[zlibpng] libraries built"

LIBDIR="${SYSROOT}/lib/wasm32-emscripten"
INCDIR="${SYSROOT}/include"

mkdir -p "$PREFIX/lib" "$PREFIX/include"

for f in "$LIBDIR"/libz.a "$LIBDIR"/libz.so; do
  [ -e "$f" ] || continue
  cp -f "$f" "$PREFIX/lib/" 2>/dev/null || true
done
for f in "$LIBDIR"/libpng*.a "$LIBDIR"/libpng*.so; do
  [ -e "$f" ] || continue
  cp -f "$f" "$PREFIX/lib/" 2>/dev/null || true
done

for h in zlib.h zconf.h; do
  [ -f "$INCDIR/$h" ] && cp -f "$INCDIR/$h" "$PREFIX/include/"
done
[ -d "$INCDIR/png" ] && cp -rf "$INCDIR/png" "$PREFIX/include/"

mkdir -p "$PREFIX/lib/cmake/ZLIB" "$PREFIX/lib/cmake/PNG"

cat > "$PREFIX/lib/cmake/ZLIB/ZLIBConfig.cmake" <<'CMAKE'
# Backs the Emscripten sysroot port with the prefix layout find_package wants.
set(ZLIB_FOUND TRUE)
set(ZLIB_INCLUDE_DIR  "${CMAKE_CURRENT_LIST_DIR}/../../../include")
set(ZLIB_INCLUDE_DIRS "${ZLIB_INCLUDE_DIR}")
set(ZLIB_LIBRARY      "${CMAKE_CURRENT_LIST_DIR}/../../../lib/libz.a")
set(ZLIB_LIBRARIES    "${ZLIB_LIBRARY}")
if(NOT TARGET ZLIB::ZLIB)
  add_library(ZLIB::ZLIB STATIC IMPORTED GLOBAL)
  set_target_properties(ZLIB::ZLIB PROPERTIES
    IMPORTED_LOCATION "${ZLIB_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${ZLIB_INCLUDE_DIR}")
endif()
CMAKE

PNG_LIB=$(ls "$PREFIX/lib"/libpng*.a 2>/dev/null | head -1)
[ -n "$PNG_LIB" ] || PNG_LIB="$PREFIX/lib/libpng.a"

cat > "$PREFIX/lib/cmake/PNG/PNGConfig.cmake" <<'CMAKE'
set(PNG_FOUND TRUE)
set(PNG_INCLUDE_DIR  "${CMAKE_CURRENT_LIST_DIR}/../../../include")
set(PNG_INCLUDE_DIRS "${PNG_INCLUDE_DIR}")
set(PNG_LIBRARY      "@PNG_LIB_PATH@")
set(PNG_LIBRARIES    "${PNG_LIBRARY}")
if(NOT TARGET PNG::PNG)
  add_library(PNG::PNG STATIC IMPORTED GLOBAL)
  set_target_properties(PNG::PNG PROPERTIES
    IMPORTED_LOCATION "@PNG_LIB_PATH@"
    INTERFACE_INCLUDE_DIRECTORIES "${PNG_INCLUDE_DIR}"
    INTERFACE_LINK_LIBRARIES ZLIB::ZLIB)
endif()
CMAKE

# The quoted heredoc above keeps "${...}" literal for CMake; the one real
# path is substituted here.
sed -i "s|@PNG_LIB_PATH@|$PNG_LIB|g" "$PREFIX/lib/cmake/PNG/PNGConfig.cmake"

echo "[zlibpng] done"
ls -la "$PREFIX/lib"/libz.a "$PREFIX/lib"/libpng*.a 2>/dev/null || true
