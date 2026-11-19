# C ABI bridge: the only code that touches libslic3r on behalf of the host.
# Links against libslic3r only; GUI/wxWidgets/OpenGL are out of scope.

add_library(bsw_bridge STATIC
  slicer.cpp
)

target_include_directories(bsw_bridge PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(bsw_bridge PUBLIC
  libslic3r
)

target_compile_features(bsw_bridge PUBLIC cxx_std_17)
