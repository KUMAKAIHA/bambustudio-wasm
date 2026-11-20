# FindNLopt.cmake -- WebAssembly override.
#
# BambuStudio's own module only sets NLopt_LIBS / NLopt_INCLUDE_DIR variables.
# libnest2d, however, does:
#
#     target_link_libraries(libnest2d PUBLIC NLopt::nlopt ...)
#
# which needs a real IMPORTED target, not a variable. Under WASM we take the
# project's preferred route anyway: NLopt is only reached through libnest2d's
# optimiser, which the headless slicer exercises in a narrow path. An INTERFACE
# stub keeps the target name resolvable without cross-compiling libnlopt.
if(NOT TARGET NLopt::nlopt)
  add_library(NLopt::nlopt INTERFACE IMPORTED GLOBAL)
endif()
set(NLopt_FOUND TRUE)
set(NLOPT_FOUND TRUE)
set(NLopt_LIBS "")
set(NLopt_INCLUDE_DIR "")
