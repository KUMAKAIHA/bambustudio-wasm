# WASM dependency discovery.
#
# BambuStudio's build assumes system-installed Boost/CGAL/TBB. Under Emscripten
# there is no system: every dependency is cross-compiled into the WASM sysroot
# first, then pointed at through the environment variables below.

# Boost built for WASM by scripts/build-deps.sh
if(DEFINED ENV{BOOST_WASM_ROOT})
  set(BOOST_ROOT "$ENV{BOOST_WASM_ROOT}")
  set(Boost_INCLUDE_DIR "$ENV{BOOST_WASM_ROOT}/include")
  set(Boost_LIBRARY_DIR "$ENV{BOOST_WASM_ROOT}/lib")
endif()

# oneTBB built for WASM
if(DEFINED ENV{TBB_WASM_ROOT})
  set(TBB_ROOT "$ENV{TBB_WASM_ROOT}")
endif()

# Catch2 is only used by the unit tests, which are disabled for WASM.
set(Catch2_FOUND TRUE)
