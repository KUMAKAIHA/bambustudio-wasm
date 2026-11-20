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

echo "[zlibpng] building ports"
embuilder build zlib libpng

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

cat > "$PREFIX/lib/cmake/PNG/PNGConfig.cmake" <<CMAKE
set(PNG_FOUND TRUE)
set(PNG_INCLUDE_DIR  "${CMAKE_CURRENT_LIST_DIR}/../../../include")
set(PNG_INCLUDE_DIRS "${PNG_INCLUDE_DIR}")
set(PNG_LIBRARY      "$PNG_LIB")
set(PNG_LIBRARIES    "${PNG_LIBRARY}")
if(NOT TARGET PNG::PNG)
  add_library(PNG::PNG STATIC IMPORTED GLOBAL)
  set_target_properties(PNG::PNG PROPERTIES
    IMPORTED_LOCATION "$PNG_LIB"
    INTERFACE_INCLUDE_DIRECTORIES "${PNG_INCLUDE_DIR}"
    INTERFACE_LINK_LIBRARIES ZLIB::ZLIB)
endif()
CMAKE

echo "[zlibpng] done"
ls -la "$PREFIX/lib"/libz.a "$PREFIX/lib"/libpng*.a 2>/dev/null || true
