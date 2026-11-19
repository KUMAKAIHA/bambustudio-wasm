#!/usr/bin/env bash
# Cross-compile BambuStudio's native dependencies to WASM.
#
# libslic3r's CMake calls find_package on all of these unconditionally, so
# every one has to exist as a WASM object before configure will succeed.
#
# The recipes follow the proven set published by Hiosdra/OrcaWasm: OrcaSlicer
# is a fork of the same libslic3r lineage, so the dependency surface and the
# known-good configure flags are identical.
set -euo pipefail

: "${BOOST_VERSION:=1.83.0}"
: "${GMP_VERSION:=6.3.0}"
: "${MPFR_VERSION:=4.2.1}"
: "${CGAL_VERSION:=5.6.2}"
: "${ONETBB_VERSION:=v2021.13.2}"
: "${EXPAT_VERSION:=2.5.0}"
: "${NLOPT_VERSION:=2.7.1}"
: "${CEREAL_VERSION:=1.3.2}"

ROOT="$(pwd)"
INSTALL="$ROOT/deps-install"
mkdir -p "$INSTALL"

NPROC=$(nproc)

# These flags are Emscripten-specific (-sSUPPORT_LONGJMP is an emcc setting the
# host cc does not recognise). They must NEVER be exported globally: the
# header-only installs below (eigen, nlohmann, cereal, CGAL) deliberately run
# plain host cmake, and a leaked -s flag makes their compiler-ABI probe fail
# with "cc: error: unrecognized command-line option".
EM_CFLAGS="-sSUPPORT_LONGJMP=wasm -pthread -O2"
EM_CXXFLAGS="-fwasm-exceptions -pthread -O2"

echo "[deps] install root: $INSTALL"

# ── GMP ──────────────────────────────────────────────────────────────────────
if [ ! -f "$INSTALL/lib/libgmp.a" ]; then
  echo "[gmp] building $GMP_VERSION"
  DL=/tmp/deps-dl; mkdir -p "$DL"
  curl -fL --retry 3 "https://ftp.gnu.org/gnu/gmp/gmp-$GMP_VERSION.tar.xz" | tar xJ -C "$DL"
  cd "$DL/gmp-$GMP_VERSION"
  # gmp's configure probes the assembler for its label suffix, which libtool
  # cannot do under emconfigure and fails with "Cannot determine label
  # suffix". CONFIG_SITE seeds the cache variable before the probe runs;
  # --host and --disable-assembly then skip the probe entirely.
  printf 'gmp_cv_asm_label_suffix=":"\n' > /tmp/gmp_site.sh
  export gmp_cv_asm_label_suffix=":"
  CONFIG_SITE=/tmp/gmp_site.sh CFLAGS="$EM_CFLAGS" CXXFLAGS="$EM_CXXFLAGS" \
    emconfigure ./configure \
    --prefix="$INSTALL" \
    --host=wasm32-unknown-emscripten \
    --disable-shared --enable-static --disable-assembly --enable-cxx
  emmake make -j"$NPROC"
  make install
  echo "[gmp] done"
else
  echo "[gmp] cached"
fi

# ── MPFR ─────────────────────────────────────────────────────────────────────
if [ ! -f "$INSTALL/lib/libmpfr.a" ]; then
  echo "[mpfr] building $MPFR_VERSION"
  DL=/tmp/deps-dl; mkdir -p "$DL"
  curl -fL --retry 3 "https://ftp.gnu.org/gnu/mpfr/mpfr-$MPFR_VERSION.tar.xz" | tar xJ -C "$DL"
  cd "$DL/mpfr-$MPFR_VERSION"
  CFLAGS="$EM_CFLAGS" CXXFLAGS="$EM_CXXFLAGS" \
    emconfigure ./configure \
    --prefix="$INSTALL" --with-gmp="$INSTALL" \
    --disable-shared --enable-static
  emmake make -j"$NPROC"
  make install
  echo "[mpfr] done"
else
  echo "[mpfr] cached"
fi

# ── Eigen / nlohmann / cereal ────────────────────────────────────────────────
# Header-only; the CMake install step only drops headers plus a config file so
# find_package works inside libslic3r.
if [ ! -d "$INSTALL/include/eigen3" ]; then
  echo "[eigen] installing"
  curl -fsSL "https://gitlab.com/libeigen/eigen/-/archive/5.0.1/eigen-5.0.1.tar.gz" | tar xz -C /tmp
  # Header-only install: plain HOST cmake. Passing Emscripten flags here makes
  # the compiler-ABI probe fail with an unrecognised-option error.
  env -u CFLAGS -u CXXFLAGS -u LDFLAGS \
    cmake -S /tmp/eigen-5.0.1 -B /tmp/eigen-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" -DBUILD_TESTING=OFF
  cmake --build /tmp/eigen-build --target install
  echo "[eigen] done"
else
  echo "[eigen] cached"
fi

if [ ! -f "$INSTALL/share/cmake/nlohmann_json/nlohmann_jsonConfig.cmake" ]; then
  echo "[nlohmann] installing"
  git clone --depth 1 --branch v3.11.3 https://github.com/nlohmann/json.git /tmp/nlohmann
  env -u CFLAGS -u CXXFLAGS -u LDFLAGS \
    cmake -S /tmp/nlohmann -B /tmp/nlohmann-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" -DJSON_BuildTests=OFF -DJSON_Install=ON
  cmake --build /tmp/nlohmann-build --target install
  echo "[nlohmann] done"
else
  echo "[nlohmann] cached"
fi

if [ ! -f "$INSTALL/share/cmake/cereal/cerealConfig.cmake" ]; then
  echo "[cereal] installing"
  git clone --depth 1 --branch v$CEREAL_VERSION https://github.com/USCiLab/cereal.git /tmp/cereal
  env -u CFLAGS -u CXXFLAGS -u LDFLAGS \
    cmake -S /tmp/cereal -B /tmp/cereal-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" -DJUST_INSTALL_CEREAL=ON \
    -DSKIP_PERFORMANCE_COMPARISON=ON -DBUILD_SANDBOX=OFF -DBUILD_DOC=OFF
  cmake --build /tmp/cereal-build --target install
  echo "[cereal] done"
else
  echo "[cereal] cached"
fi

# ── EXPAT ────────────────────────────────────────────────────────────────────
if [ ! -f "$INSTALL/lib/libexpat.a" ]; then
  echo "[expat] building $EXPAT_VERSION"
  curl -fsSL "https://github.com/libexpat/libexpat/releases/download/R_${EXPAT_VERSION//./_}/expat-$EXPAT_VERSION.tar.xz" | tar xJ -C /tmp
  emcmake cmake -S "/tmp/expat-$EXPAT_VERSION" -B /tmp/expat-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" \
    -DEXPAT_BUILD_TOOLS=OFF -DEXPAT_BUILD_EXAMPLES=OFF \
    -DEXPAT_BUILD_TESTS=OFF -DEXPAT_SHARED_LIBS=OFF \
    "-DCMAKE_C_FLAGS=$EM_CFLAGS" "-DCMAKE_CXX_FLAGS=$EM_CXXFLAGS"
  emmake cmake --build /tmp/expat-build --target install
  echo "[expat] done"
else
  echo "[expat] cached"
fi

# ── NLopt ────────────────────────────────────────────────────────────────────
if [ ! -f "$INSTALL/lib/libnlopt.a" ]; then
  echo "[nlopt] building $NLOPT_VERSION"
  curl -fsSL "https://github.com/stevengj/nlopt/archive/v$NLOPT_VERSION.tar.gz" | tar xz -C /tmp
  emcmake cmake -S "/tmp/nlopt-$NLOPT_VERSION" -B /tmp/nlopt-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" \
    -DNLOPT_PYTHON=OFF -DNLOPT_OCTAVE=OFF -DNLOPT_SWIG=OFF -DNLOPT_MATLAB=OFF \
    -DNLOPT_GUILE=OFF -DNLOPT_JAVA=OFF -DNLOPT_CXX=ON -DBUILD_SHARED_LIBS=OFF \
    "-DCMAKE_C_FLAGS=$EM_CFLAGS" "-DCMAKE_CXX_FLAGS=$EM_CXXFLAGS"
  emmake cmake --build /tmp/nlopt-build --target install
  echo "[nlopt] done"
else
  echo "[nlopt] cached"
fi

# ── Boost ────────────────────────────────────────────────────────────────────
if [ ! -d "$INSTALL/include/boost" ]; then
  echo "[boost] building $BOOST_VERSION"
  BV="${BOOST_VERSION//./_}"
  mkdir -p /tmp/boost
  curl -fL --retry 3 "https://archives.boost.org/release/$BOOST_VERSION/source/boost_$BV.tar.gz" | tar xz -C /tmp/boost
  cd "/tmp/boost/boost_$BV"
  ./bootstrap.sh --with-toolset=clang
  # b2 needs an explicit emscripten toolset; without it it picks the host gcc
  # and produces native objects that poison the WASM link with confusing
  # undefined-symbol errors far from the real cause.
  printf 'using clang : emscripten : em++ :\n<archiver>emar\n<ranlib>emranlib ;\n' > ~/user-config.jam
  ./b2 \
    toolset=clang-emscripten variant=release link=static \
    threading=multi --layout=system --prefix="$INSTALL" \
    --with-atomic --with-chrono --with-date_time --with-filesystem \
    --with-iostreams --with-locale --with-log --with-nowide \
    --with-program_options --with-regex --with-system --with-thread \
    "define=BOOST_LOG_WITHOUT_SYSLOG=1" \
    "define=BOOST_LOG_NO_THREADS=1" \
    "cxxflags=-fwasm-exceptions -pthread" \
    -j"$NPROC" install
  echo "[boost] done"
else
  echo "[boost] cached"
fi

# ── oneTBB ───────────────────────────────────────────────────────────────────
if [ ! -d "$INSTALL/include/tbb" ]; then
  echo "[tbb] building $ONETBB_VERSION"
  rm -rf /tmp/onetbb
  git clone --depth 1 --branch "$ONETBB_VERSION" https://github.com/oneapi-src/oneTBB.git /tmp/onetbb
  emcmake cmake -S /tmp/onetbb -B /tmp/tbb-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" \
    -DCMAKE_BUILD_TYPE=Release \
    -DTBB_TEST=OFF -DTBB_EXAMPLES=OFF -DTBB_STRICT=OFF -DTBBMALLOC_BUILD=OFF
  emmake cmake --build /tmp/tbb-build -j"$NPROC"
  emmake cmake --install /tmp/tbb-build
  echo "[tbb] done"
else
  echo "[tbb] cached"
fi

# ── CGAL config ──────────────────────────────────────────────────────────────
# Header-only. Plain cmake (not emcmake): this only installs headers and the
# CMake config, no cross-compiled objects are produced.
if [ ! -f "$INSTALL/lib/cmake/CGAL/CGALConfig.cmake" ]; then
  echo "[cgal] installing $CGAL_VERSION"
  curl -fL --retry 3 "https://github.com/CGAL/cgal/releases/download/v$CGAL_VERSION/CGAL-$CGAL_VERSION.tar.xz" | tar xJ -C /tmp
  env -u CFLAGS -u CXXFLAGS -u LDFLAGS \
    cmake -S "/tmp/CGAL-$CGAL_VERSION" -B /tmp/cgal-build -G Ninja \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" -DCMAKE_BUILD_TYPE=Release \
    -DGMP_INCLUDE_DIR="$INSTALL/include" -DGMP_LIBRARIES="$INSTALL/lib/libgmp.a" \
    -DMPFR_INCLUDE_DIR="$INSTALL/include" -DMPFR_LIBRARIES="$INSTALL/lib/libmpfr.a"
  cmake --build /tmp/cgal-build --target install
  echo "[cgal] done"
else
  echo "[cgal] cached"
fi

echo
echo "[deps] installed into $INSTALL"
ls "$INSTALL/lib"/*.a 2>/dev/null | head -20
