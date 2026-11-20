# FindFreetype.cmake -- stub for the WebAssembly build.
#
# FreeType backs on-canvas text rendering, a GUI concern. libslic3r only links
# it to satisfy the 3D text shape feature, which is compiled out under WASM.
if(NOT TARGET Freetype::Freetype)
  add_library(Freetype::Freetype INTERFACE IMPORTED GLOBAL)
endif()
set(Freetype_FOUND TRUE)
set(FREETYPE_FOUND TRUE)
set(FREETYPE_LIBRARIES "")
set(FREETYPE_INCLUDE_DIRS "")
