# Findlibnoise.cmake -- WebAssembly override.
#
# libnoise backs the structured fuzzy-skin noise generators. libslic3r links
# noise::noise unconditionally, so the target has to exist even when the library
# is not built. Provide an INTERFACE stub rather than cross-compiling the whole
# dependency for one optional texture path.
if(NOT TARGET noise::noise)
  add_library(noise::noise INTERFACE IMPORTED GLOBAL)
endif()
set(libnoise_FOUND TRUE)
set(LIBNOISE_FOUND TRUE)
