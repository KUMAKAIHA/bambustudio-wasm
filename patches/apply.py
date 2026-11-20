#!/usr/bin/env python3
"""
Apply WebAssembly compatibility patches to the BambuStudio source tree.

BambuStudio has no upstream WASM build support. These patches are the minimum
set required to make libslic3r (the slicing kernel) compile under Emscripten
and run in a browser.

Design
------
* Every patch is anchored on an exact string that exists in the pinned
  BambuStudio tag. If the anchor is missing we FAIL LOUDLY rather than
  silently skipping -- a silently-skipped patch produces a binary that
  crashes at runtime, far more expensive to debug than a red CI run.
* Patches are idempotent: applying twice is a no-op.
* --check dry-runs: reports what would change, writes nothing.

Run from the repository root:

    python3 patches/apply.py [--check]

The source tree is expected at  $BSW_SRC  (default: ./BambuStudio)
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("BSW_SRC", ROOT / "BambuStudio"))

_parser = argparse.ArgumentParser()
_parser.add_argument("--check", action="store_true")
_args = _parser.parse_args()
DRY_RUN = _args.check

_failures: list[str] = []


def _log(msg: str) -> None:
    print(msg)


def _first_line(text: str) -> str:
    """First meaningful line of a replacement block, used as an idempotency marker."""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("//") and not line.startswith("#") and not line.startswith("/*"):
            return line
    return ""


def patch(rel: str, replacements: list[tuple[str, str, str]]) -> None:
    """Apply exact-string replacements to one file.

    replacements: list of (anchor, replacement, description).
    The anchor must appear exactly once, or the patch is rejected.
    """
    path = SRC / rel
    if not path.exists():
        _failures.append(rel + ": file not found")
        return
    text = path.read_text(encoding="utf-8")
    original = text
    for anchor, repl, desc in replacements:
        # Idempotency must test for the WHOLE replacement, not a marker line.
        # Two failure modes ruled out a line-based check:
        #   1. Testing "is the anchor still present" is unsound -- anchors
        #      survive inside their own replacement ("#else // _WIN32" appears in
        #      both the new #elif arm and the untouched #else arm), so a second
        #      run re-appended the block.
        #   2. Testing the replacement's first line is unsound for a different
        #      reason: several replacements legitimately share a first line
        #      (CGAL, OpenCV and OCCT all begin "if(NOT SLIC3R_WASM)"), so once
        #      the first had been applied the other two were skipped silently --
        #      which is exactly how OpenCV slipped through to CMake configure.
        # A full-block test is unambiguous.
        if repl in text:
            _log("  OK   " + rel + "  [" + desc + ": already applied]")
            continue
        count = text.count(anchor)
        if count == 0:
            _failures.append(rel + ": anchor not found (" + desc + ")")
            continue
        if count > 1:
            _failures.append(rel + ": anchor ambiguous, " + str(count) + " matches (" + desc + ")")
            continue
        text = text.replace(anchor, repl, 1)
        _log("  OK   " + rel + "  [" + desc + "]")
    if text == original:
        return
    if DRY_RUN:
        _log("  WOULD WRITE " + rel)
        return
    path.write_text(text, encoding="utf-8")
    _log("  WROTE " + rel)


def append_once(rel: str, marker: str, block: str, desc: str) -> None:
    path = SRC / rel
    if not path.exists():
        _failures.append(rel + ": file not found (" + desc + ")")
        return
    text = path.read_text(encoding="utf-8")
    if marker in text:
        _log("  OK   " + rel + "  [" + desc + ": already present]")
        return
    if DRY_RUN:
        _log("  WOULD APPEND " + rel + "  [" + desc + "]")
        return
    path.write_text(text + block, encoding="utf-8")
    _log("  APPENDED " + rel + "  [" + desc + "]")


# 1. Top-level CMakeLists.txt -- declare the WASM build switch
def patch_top_cmake() -> None:
    patch("CMakeLists.txt", [(
        "project(BambuStudio)",
        """project(BambuStudio)

# -- WebAssembly build switch -------------------------------------------------
# Consumed by the patches below to make heavy, WASM-incompatible dependencies
# conditional. Off by default; CI turns it on with -DSLIC3R_WASM=ON.
option(SLIC3R_WASM "Build the slicing kernel for WebAssembly (Emscripten)" OFF)""",
        "SLIC3R_WASM option",
    )])


# 2. libslic3r/CMakeLists.txt -- make CGAL / OpenCV / OCCT conditional
#
#    These pull in desktop-only libraries. The headless slicing kernel needs
#    none of them:
#      * OCCT   -> only the GUI's STEP/IGES importer
#      * OpenCV -> only GUI image features
#      * CGAL   -> a few helpers; BambuStudio routes most geometry through its
#                  own code, and our cmake shim covers the remaining pieces
def patch_libslic3r_cmake() -> None:
    patch("src/libslic3r/CMakeLists.txt", [
        (
            "find_package(CGAL REQUIRED)",
            """if(NOT SLIC3R_WASM)
  find_package(CGAL REQUIRED)
else()
  # CGAL is header-only but its CMake config ships a full dependency graph
  # (GMP/MPFR/Boost/Qhull) that does not survive cross-compilation. The WASM
  # target still needs the name to exist, because libslic3r_cgal links it and
  # reads its INTERFACE_COMPILE_OPTIONS.
  if(NOT TARGET CGAL::CGAL)
    add_library(CGAL::CGAL INTERFACE IMPORTED GLOBAL)
  endif()
endif()""",
            "CGAL conditional",
        ),
        (
            "find_package(OpenCV REQUIRED core)",
            """if(NOT SLIC3R_WASM)
  # OpenCV is GUI-only (image features); the headless kernel omits it.
  find_package(OpenCV REQUIRED core)
endif()""",
            "OpenCV conditional",
        ),
        (
            "find_package(OpenCASCADE REQUIRED)",
            """if(NOT SLIC3R_WASM)
  # OCCT is GUI-only (STEP/IGES import); the headless kernel omits it.
  find_package(OpenCASCADE REQUIRED)
endif()""",
            "OCCT conditional",
        ),
        (
            "find_package(assimp REQUIRED)",
            """if(NOT SLIC3R_WASM)
  # assimp is GUI-only (mesh import formats); the headless kernel omits it.
  find_package(assimp REQUIRED)
endif()""",
            "assimp conditional",
        ),
    ])


# 3. Platform.cpp -- Emscripten is not an enumerated desktop platform, so the
#    fallback branch's static_assert(false) fires and kills the build.
def patch_platform() -> None:
    patch("src/libslic3r/Platform.cpp", [(
        """#else
	// This should not happen.
    BOOST_LOG_TRIVIAL(info) << "Platform: Unknown";
	static_assert(false, "Unknown platform detected");
	s_platform 		  = Platform::Unknown;
	s_platform_flavor = PlatformFlavor::Unknown;
#endif""",
        """#else
	// Emscripten is not a desktop platform, but the kernel behaves exactly
	// like POSIX here, so "Unknown" is correct and the assert must not fire.
    BOOST_LOG_TRIVIAL(info) << "Platform: Unknown";
#if !defined(__EMSCRIPTEN__)
	static_assert(false, "Unknown platform detected");
#endif
	s_platform 		  = Platform::Unknown;
	s_platform_flavor = PlatformFlavor::Unknown;
#endif""",
        "Platform static_assert guard",
    )])


# 4. Thread.cpp -- Emscripten implements no pthread_setname_np at all, neither
#    the 1-arg (self) nor the 2-arg (handle) form, so the whole POSIX arm must
#    be replaced.
def patch_thread() -> None:
    patch("src/libslic3r/Thread.cpp", [(
        "#else // _WIN32",
        """#elif defined(__EMSCRIPTEN__)

// Emscripten provides no pthread_setname_np (neither the self nor the handle
// form). Thread names exist only for debugging, so these are no-ops.
bool set_thread_name(std::thread &, const char *) { return false; }
bool set_thread_name(boost::thread &, const char *) { return false; }
bool set_current_thread_name(const char *) { return false; }
std::optional<std::string> get_current_thread_name() { return std::nullopt; }

#else // _WIN32""",
        "Emscripten thread-name stubs",
    )])


# 5. Arachne/WallToolPaths.hpp -- WallToolPathsParams members carry no default
#    initialisers. On desktop this is latent UB that happens to read as zero;
#    under Emscripten it yields garbage that feeds NaN geometry into the wall
#    generator, which traps the module at runtime.
def patch_arachne() -> None:
    patch("src/libslic3r/Arachne/WallToolPaths.hpp", [(
        """class WallToolPathsParams
{
public:
    float   min_bead_width;
    float   min_feature_size;
    float   wall_transition_length;
    float   wall_transition_angle;
    float   wall_transition_filter_deviation;
    int     wall_distribution_count;
};""",
        """class WallToolPathsParams
{
public:
    // Defaults are required: the GUI fills these from presets, but the headless
    // path can construct the struct and use it before every field is assigned.
    // Without initialisers that is UB, which under Emscripten yields NaN
    // geometry that traps the module.
    float   min_bead_width                   = 0.34f;
    float   min_feature_size                 = 0.20f;
    float   wall_transition_length           = 1.0f;
    float   wall_transition_angle            = 10.0f;
    float   wall_transition_filter_deviation = 0.25f;
    int     wall_distribution_count          = 1;
};""",
        "WallToolPathsParams default init",
    )])


# 6. Bridge injection -- hook the C ABI bridge into the top-level build.
BRIDGE_BLOCK = """
# -- WebAssembly bridge --------------------------------------------------------
# Present only when CI checks this repository out as a sibling of the
# BambuStudio source. Harmless in a plain desktop build.
if(SLIC3R_WASM AND EXISTS "$CMAKE_CURRENT_SOURCE_DIR/../bridge/CMakeLists.txt")
  add_subdirectory("$CMAKE_CURRENT_SOURCE_DIR/../bridge" bridge)
endif()
"""


# 7. libslic3r/CMakeLists.txt -- guard the CGAL option-inspection block.
#
#    That block reads INTERFACE_COMPILE_OPTIONS off CGAL::CGAL and strips
#    -frounding-math from it. Under SLIC3R_WASM the target is a bare INTERFACE
#    stub with no properties set, and get_target_property() hard-errors on a
#    target whose property was never set. Skipping the block is correct --
#    there are no CGAL compile options to reset.
def patch_cgal_options() -> None:
    patch("src/libslic3r/CMakeLists.txt", [(
        'get_target_property(_cgal_tgt CGAL::CGAL ALIASED_TARGET)',
        'if(NOT SLIC3R_WASM)\nget_target_property(_cgal_tgt CGAL::CGAL ALIASED_TARGET)',
        "CGAL option block open",
    ), (
        '    target_compile_options(libslic3r_cgal PRIVATE "${_opts_bad}")\nendif()',
        '    target_compile_options(libslic3r_cgal PRIVATE "${_opts_bad}")\nendif()\nelse()\n  # WASM: CGAL::CGAL is an empty INTERFACE stub, so there are no compile\n  # options to inspect or reset. Keep the variable set for the link line.\n  set(_cgal_tgt CGAL::CGAL)\nendif()',
        "CGAL option block close",
    )])


def patch_bridge() -> None:
    append_once(
        "CMakeLists.txt",
        "add_subdirectory(\"$CMAKE_CURRENT_SOURCE_DIR/../bridge\" bridge)",
        BRIDGE_BLOCK,
        "bridge injection",
    )


def main() -> int:
    if not SRC.exists():
        print("FATAL: BambuStudio source not found at " + str(SRC), file=sys.stderr)
        print("Set BSW_SRC to the checkout path.", file=sys.stderr)
        return 2

    print("bambustudio-wasm patcher -- source: " + str(SRC))
    print("mode: " + ("DRY RUN" if DRY_RUN else "APPLY"))
    print()

    for step, fn in [
        ("[1] top-level CMakeLists.txt", patch_top_cmake),
        ("[2] libslic3r/CMakeLists.txt", patch_libslic3r_cmake),
        ("[3] Platform.cpp", patch_platform),
        ("[4] Thread.cpp", patch_thread),
        ("[5] Arachne/WallToolPaths.hpp", patch_arachne),
        ("[6] CGAL option block guard", patch_cgal_options),
        ("[7] bridge injection", patch_bridge),
    ]:
        _log(step)
        fn()

    print()
    if _failures:
        print("FAILED -- " + str(len(_failures)) + " problem(s):", file=sys.stderr)
        for f in _failures:
            print("  - " + f, file=sys.stderr)
        print()
        print("These anchors are pinned to BambuStudio v02.09.01.70. If upstream", file=sys.stderr)
        print("reformatted a file, update the anchor rather than deleting the patch", file=sys.stderr)
        print("-- a silently-skipped patch yields a binary that traps at runtime", file=sys.stderr)
        print("instead of failing here.", file=sys.stderr)
        return 1

    print("All patches applied cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
