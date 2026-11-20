# FindOpenCV.cmake -- stub for the WebAssembly build.
#
# OpenCV is pulled in for the GUI's image features only. The headless slicing
# kernel compiles those paths out under SLIC3R_WASM, so an empty imported
# target is enough to satisfy libslic3r's find_package and target_link_libraries
# calls without dragging a 200 MB desktop library into the WASM link.
if(NOT TARGET opencv_world)
  add_library(opencv_world INTERFACE IMPORTED GLOBAL)
endif()
set(OpenCV_FOUND TRUE)
set(OpenCV_LIBS opencv_world)
set(OpenCV_LIBRARIES opencv_world)
set(OpenCV_INCLUDE_DIRS "")
