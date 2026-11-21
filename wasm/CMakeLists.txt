# Final Emscripten module: links libslic3r + bridge into <name>.js/.wasm.

add_executable(bsw_engine "${CMAKE_CURRENT_SOURCE_DIR}/empty_main.cpp")

target_link_libraries(bsw_engine PRIVATE bsw_bridge)

set(BSW_OUTPUT_NAME "bambu-slicer" CACHE STRING "Output artifact base name")

target_link_options(bsw_engine PRIVATE
  -O3
  --profiling-funcs
  # The -Wl,-u roots that used to live here are gone: -sEXPORTED_FUNCTIONS
  # already marks every listed symbol as needed and emits the matching --export
  # for each. Passing both meant the linker saw -u and --export for the same
  # name, and the resulting table contained neither.

  -sALLOW_MEMORY_GROWTH=1
  -sMALLOC=emmalloc
  -sSTACK_SIZE=16777216
  -sINITIAL_MEMORY=268435456
  -sMAXIMUM_MEMORY=4294967296
  -sABORTING_MALLOC=0
  -sENVIRONMENT=web,worker
  -sMODULARIZE=1
  # EXPORT_ES6 is deliberately off. With it Emscripten emits an ES module whose
  # default export hides the wasm export table behind a wrapper; without it the
  # glue assigns the factory to globalThis.BambuModule and the C symbols stay
  # addressable, which is what host.js expects.
  -sEXPORT_NAME=BambuModule
  -fwasm-exceptions
  -sSUPPORT_LONGJMP=wasm
  -pthread
  -sUSE_PTHREADS=1
  # Pre-spawn the pthread pool: the slicer's calling thread never yields to the
  # JS event loop while blocked inside print.process(), so a lazily created
  # worker never materialises and any join on it hangs forever.
  -sPTHREAD_POOL_SIZE=navigator.hardwareConcurrency+4
  -sPTHREAD_POOL_SIZE_STRICT=2
  # No --preload-file: the headless engine touches only /tmp for input/output.
  -sFORCE_FILESYSTEM=1
  "-sEXPORTED_FUNCTIONS=[\
'_bsw_session_create',\
'_bsw_session_destroy',\
'_bsw_init',\
'_bsw_model_load',\
'_bsw_model_export_stl',\
'_bsw_model_transform',\
'_bsw_model_orient',\
'_bsw_model_arrange',\
'_bsw_model_info',\
'_bsw_slice',\
'_bsw_cancel',\
'_bsw_set_progress_callback',\
'_bsw_asset_size',\
'_bsw_asset_read',\
'_bsw_last_error',\
'_bsw_capabilities',\
'_bsw_free',\
'_malloc',\
'_free'\
]"
  "-sEXPORTED_RUNTIME_METHODS=[\
'ccall',\
'cwrap',\
'getValue',\
'setValue',\
'UTF8ToString',\
'stringToUTF8',\
'lengthBytesUTF8',\
'HEAP8',\
'HEAPU8',\
'HEAP32',\
'HEAPU32',\
'addFunction',\
'removeFunction'\
]"
)

set_target_properties(bsw_engine PROPERTIES
  OUTPUT_NAME "${BSW_OUTPUT_NAME}"
  SUFFIX ".js"
)

add_custom_command(TARGET bsw_engine POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_CURRENT_SOURCE_DIR}/../artifacts"
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${CMAKE_CURRENT_BINARY_DIR}/${BSW_OUTPUT_NAME}.js"
    "${CMAKE_CURRENT_SOURCE_DIR}/../artifacts/${BSW_OUTPUT_NAME}.js"
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
    "${CMAKE_CURRENT_BINARY_DIR}/${BSW_OUTPUT_NAME}.wasm"
    "${CMAKE_CURRENT_SOURCE_DIR}/../artifacts/${BSW_OUTPUT_NAME}.wasm"
  COMMENT "Copying WASM artifacts to artifacts/"
)
