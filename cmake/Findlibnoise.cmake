# Findlibnoise.cmake -- WebAssembly override.
#
# libnoise backs the structured fuzzy-skin noise generators. libslic3r links
# noise::noise unconditionally, so the target has to exist even when the library
# is not built. Provide an INTERFACE stub rather than cross-compiling the whole
# dependency for one optional texture path.
# Build against the real cross-compiled libnoise rather than an empty stub:
# libslic3r/FuzzySkin.cpp calls noise::module for fuzzy-skin perturbation, and
# that code path is reachable in headless slicing.
set(_libnoise_root "$ENV{DEPS_INSTALL}")
if(NOT _libnoise_root)
  set(_libnoise_root "$ENV{BOOST_WASM_ROOT}")
endif()
if(NOT TARGET noise::noise)
  if(EXISTS "${_libnoise_root}/lib/liblibnoise_static.a")
    add_library(noise::noise STATIC IMPORTED GLOBAL)
    set_target_properties(noise::noise PROPERTIES
      IMPORTED_LOCATION "${_libnoise_root}/lib/liblibnoise_static.a"
      # FuzzySkin.cpp includes "noise.h" directly, and the package puts its
      # headers under include/libnoise/, so both roots are on the search path.
      INTERFACE_INCLUDE_DIRECTORIES "${_libnoise_root}/include;${_libnoise_root}/include/libnoise")
  else()
    add_library(noise::noise INTERFACE IMPORTED GLOBAL)
  endif()
endif()
set(libnoise_FOUND TRUE)
set(LIBNOISE_FOUND TRUE)
