#!/usr/bin/env bash
# Cross-compile BambuStudio's native dependencies to WASM.
#
# Everything here is required unconditionally by BambuStudio's CMake:
#   Boost      -- filesystem, thread, log, locale, regex, chrono, atomic
#   GMP/MPFR   -- exact rational arithmetic used by the geometry kernel
#   oneTBB     -- the parallel primitives the slicer is built around
#
# Each is installed into deps-install/<name> and pointed at by the environment
# variables exported in the workflow.
set -euo pipefail

: "${BOOST_VERSION:=1.84.0}"
: "${GMP_VERSION:=6.3.0}"
: "${MPFR_VERSION:=4.2.1}"
: "${ONETBB_VERSION:=v2021.13.2}"

ROOT="$(pwd)"
INSTALL="$ROOT/deps-install"
mkdir -p "$INSTALL"

EM_FLAGS="-fwasm-exceptions -pthread -O2"
EM_CFLAGS="-sSUPPORT_LONGJMP=wasm -pthread -O2"

# helper: run emconfigure/emmake with a private build dir
NPROC="$(nproc)"

# ── GMP ───────────────────────────────────────────────────────────────────────
if [ ! -f "$INSTALL/gmp/lib/libgmp.a" ]; then
  echo "[gmp] building $GMP_VERSION"
  cd /tmp
  curl -fsSL --retry 3 -o gmp.tar.xz "https://ftp.gnu.org/gnu/gmp/gmp-$GMP_VERSION.tar.xz"
  tar xf gmp.tar.xz
  cd "gmp-$GMP_VERSION"
  emconfigure ./configure \
    --disable-shared --enable-static \
    --disable-assembly \
    --prefix="$INSTALL/gmp" \
    CFLAGS="$EM_CFLAGS"
  emmake make -j"$NPROC"
  emmake make install
  echo "[gmp] done"
else
  echo "[gmp] cached"
fi

# ── MPFR ──────────────────────────────────────────────────────────────────────
if [ ! -f "$INSTALL/mpfr/lib/libmpfr.a" ]; then
  echo "[mpfr] building $MPFR_VERSION"
  cd /tmp
  curl -fsSL --retry 3 -o mpfr.tar.xz "https://ftp.gnu.org/gnu/mpfr/mpfr-$MPFR_VERSION.tar.xz"
  tar xf mpfr.tar.xz
  cd "mpfr-$MPFR_VERSION"
  emconfigure ./configure \
    --disable-shared --enable-static \
    --prefix="$INSTALL/mpfr" \
    --with-gmp="$INSTALL/gmp" \
    CFLAGS="$EM_CFLAGS"
  emmake make -j"$NPROC"
  emmake make install
  echo "[mpfr] done"
else
  echo "[mpfr] cached"
fi

# ── Boost ─────────────────────────────────────────────────────────────────────
if [ ! -d "$INSTALL/boost/include/boost" ]; then
  echo "[boost] building $BOOST_VERSION"
  cd /tmp
  BV="${BOOST_VERSION//./_}"
  curl -fsSL --retry 3 -o boost.tar.bz2 \
    "https://archives.boost.io/release/$BOOST_VERSION/source/boost_$BV.tar.bz2"
  tar xf boost.tar.bz2
  cd "boost_$BV"

  ./bootstrap.sh --prefix="$INSTALL/boost" --without-libraries=python

  # user-config pins the emscripten toolset; without it b2 tries gcc and
  # produces native objects that silently poison the WASM link.
  cat > user-config.jam <<'JAM'
using clang : emscripten :
  $(EMSDK)/upstream/emscripten/em++ :
  <archiver>$(EMSDK)/upstream/emscripten/emar
  <ranlib>$(EMSDK)/upstream/emscripten/emranlib
  ;
JAM

  ./b2 -j"$NPROC" \
    --user-config=user-config.jam \
    --with-filesystem --with-thread --with-log --with-locale \
    --with-regex --with-chrono --with-atomic --with-date_time \
    --with-iostreams --with-system \
    toolset=clang-emscripten \
    target-os=linux \
    link=static runtime-link=static threading=multi \
    variant=release \
    architecture=x86 address-model=32 \
    cxxflags="$EM_FLAGS" \
    cflags="$EM_CFLAGS" \
    --prefix="$INSTALL/boost" \
    install
  echo "[boost] done"
else
  echo "[boost] cached"
fi

# ── oneTBB ────────────────────────────────────────────────────────────────────
if [ ! -d "$INSTALL/tbb/include" ]; then
  echo "[tbb] building $ONETBB_VERSION"
  cd /tmp
  rm -rf onetbb
  git clone --depth 1 --branch "$ONETBB_VERSION" \
    https://github.com/oneapi-src/oneTBB.git onetbb
  cd onetbb

  emcmake cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$INSTALL/tbb" \
    -DTBB_TEST=OFF \
    -DTBB_EXAMPLES=OFF \
    -DTBB_STRICT=OFF \
    -DTBBMALLOC_BUILD=OFF \
    -DCMAKE_CXX_FLAGS="$EM_FLAGS" \
    -DCMAKE_C_FLAGS="$EM_CFLAGS"

  emmake cmake --build build -j"$NPROC"
  emmake cmake --install build
  echo "[tbb] done"
else
  echo "[tbb] cached"
fi

echo
echo "[deps] installed:"
du -sh "$INSTALL"/* 2>/dev/null || true
