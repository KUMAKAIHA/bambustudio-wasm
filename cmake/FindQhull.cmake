# FindQhull.cmake -- stub for the WebAssembly build.
#
# Qhull is a transitive requirement reached through the CGAL configuration.
# The kernel's uses of it go through code paths that SLIC3R_WASM excludes.
if(NOT TARGET Qhull::qhullcpp)
  add_library(Qhull::qhullcpp INTERFACE IMPORTED GLOBAL)
endif()
if(NOT TARGET Qhull::qhull_r)
  add_library(Qhull::qhull_r INTERFACE IMPORTED GLOBAL)
endif()
set(Qhull_FOUND TRUE)
set(QHULL_FOUND TRUE)
