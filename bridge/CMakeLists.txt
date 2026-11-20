# C ABI bridge: the only code that touches libslic3r on behalf of the host.
#
# OBJECT, not STATIC. A static archive only contributes the objects the linker
# is forced to pull in, and nothing in this build references bsw_* by name --
# they exist purely for the JS host. The archive was therefore dropped entirely
# and the module shipped with zero bsw exports (34 exports total, all Emscripten
# runtime symbols). An OBJECT library puts the objects on the link line
# unconditionally.

add_library(bsw_bridge OBJECT
  slicer.cpp
)

target_include_directories(bsw_bridge PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(bsw_bridge PUBLIC
  libslic3r
)

target_compile_features(bsw_bridge PUBLIC cxx_std_17)
