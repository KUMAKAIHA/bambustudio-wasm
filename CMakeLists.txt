cmake_minimum_required(VERSION 3.22)
project(bambustudio_wasm C CXX)

if(NOT EMSCRIPTEN)
  message(FATAL_ERROR
    "This project must be configured with Emscripten.\n"
    "Use:  emcmake cmake <source_dir> [options]")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

# Inject our Find modules before any system ones, so the WASM dependency
# locations win over whatever happens to be installed on the build machine.
list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# libslic3r's CMakeLists does include(PrecompiledHeader), and that module lives
# in BambuStudio's own cmake/modules. That path is never on CMAKE_MODULE_PATH
# when libslic3r is added directly as a subdirectory instead of going through
# the top-level BambuStudio project, so configure dies at line 4 of
# libslic3r/CMakeLists.txt with "include could not find requested file".
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/BambuStudio/cmake/modules")

# ── Force the headless WASM configuration ────────────────────────────────────
# SLIC3R_GUI stays OFF: the GUI is a separate, later concern. This target is
# the slicing kernel, which is what makes the browser port viable at all --
# libslic3r is portable C++17, wxWidgets is not.
set(SLIC3R_WASM             ON  CACHE BOOL "" FORCE)
set(SLIC3R_GUI              OFF CACHE BOOL "" FORCE)
set(SLIC3R_STATIC           ON  CACHE BOOL "" FORCE)
set(SLIC3R_BUILD_TESTS      OFF CACHE BOOL "" FORCE)
set(SLIC3R_BUILD_SANDBOXES  OFF CACHE BOOL "" FORCE)
set(SLIC3R_PCH              OFF CACHE BOOL "" FORCE)
set(BUILD_BBS_TEST_TOOLS    OFF CACHE BOOL "" FORCE)

# MCUT-only mesh boolean: OpenMeshCraft ships as a prebuilt desktop blob and
# cannot be cross-compiled here, so take the fallback backend the project
# already supports.
set(SLIC3R_ENABLE_OPENMESHCRAFT_BOOLEAN OFF CACHE BOOL "" FORCE)
set(SLIC3R_ALLOW_MCUT_BOOLEAN            ON  CACHE BOOL "" FORCE)

# Encoding verification is a contributor lint step; it needs a host binary and
# is force-disabled upstream for any cross build. Set it explicitly so
# encoding_check() is a no-op rather than an undefined command.
set(SLIC3R_ENC_CHECK OFF CACHE BOOL "" FORCE)

# ── Dependency locations, exported by build.sh ───────────────────────────────
set(BOOST_ROOT "$ENV{BOOST_WASM_ROOT}" CACHE PATH "Boost built for WASM")
set(BOOST_INC  "${BOOST_ROOT}/include" CACHE PATH "")
set(Boost_USE_STATIC_LIBS ON)
set(Boost_NO_SYSTEM_PATHS ON)
set(Boost_NO_BOOST_CMAKE  ON)

set(GMP_INCLUDE_DIR  "$ENV{GMP_WASM_INC}"  CACHE PATH "")
set(GMP_LIBRARIES    "$ENV{GMP_WASM_LIB}"  CACHE PATH "")
set(MPFR_INCLUDE_DIR "$ENV{MPFR_WASM_INC}" CACHE PATH "")
set(MPFR_LIBRARIES   "$ENV{MPFR_WASM_LIB}" CACHE PATH "")

# ── BambuStudio source ───────────────────────────────────────────────────────
set(BSW_SRC "${CMAKE_CURRENT_SOURCE_DIR}/BambuStudio" CACHE PATH
    "BambuStudio source checkout (patched by patches/apply.py)")

if(NOT EXISTS "${BSW_SRC}/src/libslic3r/CMakeLists.txt")
  message(FATAL_ERROR
    "BambuStudio source not found at ${BSW_SRC}.\n"
    "Run scripts/fetch-source.sh first, then patches/apply.py.")
endif()

# ── Bundled dependencies, in BambuStudio's own order ─────────────────────────
#
# libslic3r does NOT stand alone. Its CMakeLists references targets that only
# exist because src/CMakeLists.txt has already added these siblings:
#   encoding_check()  <- build-utils
#   libigl, mcut      <- their own subdirectories (libslic3r_cgal links both)
#   qhull, clipper*, admesh, miniz, ...  <- linked into libslic3r directly
# Adding libslic3r on its own makes configure fail with a cascade of
# "non-existent target" and "unknown command" errors that look unrelated to
# the real cause, so the whole set is added here in the upstream order.
#
# Deliberately omitted versus the desktop build:
#   libnoise  -- only reached through the GUI's fuzzy-skin preview
#   imgui / imguizmo / hidapi -- GUI only, gated behind SLIC3R_GUI upstream
# ── Targets libslic3r's siblings link without ever find_package-ing ──────────
#
# libnest2d does target_link_libraries(... NLopt::nlopt ...) but nothing in the
# tree calls find_package(NLopt) first, so the name is simply never defined.
# On desktop it works only because the system NLopt config file defines the
# imported target as a side effect of some other find. There is no equivalent
# under WASM, so define the INTERFACE target here, before any subdirectory that
# links it is added.
#
# Neither NLopt nor libnoise is on the headless critical path: NLopt backs
# libnest2d's optional nester optimisation, libnoise backs the fuzzy-skin noise
# generators. Empty INTERFACE targets keep both names resolvable.
if(NOT TARGET NLopt::nlopt)
  add_library(NLopt::nlopt INTERFACE IMPORTED GLOBAL)
endif()
if(NOT TARGET noise::noise)
  add_library(noise::noise INTERFACE IMPORTED GLOBAL)
endif()
set(NLopt_FOUND TRUE)
set(libnoise_FOUND TRUE)
set(LIBNOISE_FOUND TRUE)

set(BS_SRC "${BSW_SRC}/src")

add_subdirectory("${BS_SRC}/build-utils"    build-utils)
add_subdirectory("${BS_SRC}/admesh"         admesh)
add_subdirectory("${BS_SRC}/boost"          boost_nowide)
add_subdirectory("${BS_SRC}/clipper"        clipper)
add_subdirectory("${BS_SRC}/clipper2"       clipper2)
add_subdirectory("${BS_SRC}/miniz"          miniz)
add_subdirectory("${BS_SRC}/minilzo"        minilzo)
add_subdirectory("${BS_SRC}/glu-libtess"    glu_libtess)
add_subdirectory("${BS_SRC}/qhull"          qhull)
add_subdirectory("${BS_SRC}/semver"         semver)
add_subdirectory("${BS_SRC}/libigl"         libigl)
add_subdirectory("${BS_SRC}/mcut"           mcut)
add_subdirectory("${BS_SRC}/libnest2d"      libnest2d)
add_subdirectory("${BS_SRC}/libslic3r"      libslic3r_build)

add_subdirectory(bridge)
add_subdirectory(wasm)
