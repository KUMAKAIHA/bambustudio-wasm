# Findassimp.cmake -- stub for the WebAssembly build.
#
# assimp provides extra mesh import formats used by the GUI's file dialogs.
# The headless kernel loads STL/OBJ/3MF through its own readers.
if(NOT TARGET assimp::assimp)
  add_library(assimp::assimp INTERFACE IMPORTED GLOBAL)
endif()
set(assimp_FOUND TRUE)
set(ASSIMP_FOUND TRUE)
set(assimp_LIBRARIES "")
