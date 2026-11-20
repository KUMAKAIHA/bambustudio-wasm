# FindOpenCASCADE.cmake -- stub for the WebAssembly build.
#
# OCCT provides STEP/IGES import, which lives entirely in the GUI layer. The
# headless kernel never calls it, so the find_package only has to succeed.
if(NOT TARGET OpenCASCADE::TKernel)
  add_library(OpenCASCADE::TKernel INTERFACE IMPORTED GLOBAL)
endif()
set(OpenCASCADE_FOUND TRUE)
set(OpenCASCADE_INCLUDE_DIR "")
set(OpenCASCADE_LIBRARIES "")
