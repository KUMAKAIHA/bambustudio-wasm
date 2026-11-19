/* Emscripten requires an executable entry point even though the artifact is a
 * library the host loads. Nothing here runs in practice: the module's exported
 * functions are called directly from JavaScript. */
#include <cstdio>

int main(int, char **)
{
    std::fprintf(stderr,
        "bambustudio-wasm: this module is a library, not a standalone binary.\n");
    return 0;
}
