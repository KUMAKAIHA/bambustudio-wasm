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
D = chr(36)  # dollar sign kept out of source literals
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


# 8. ClipperZUtils.hpp -- missing include for a type it uses in its API.
#
#    The header dereferences ExPolygon (num_contours, contour, holes) but only
#    includes Point.hpp. On desktop this compiles because some earlier include in
#    the translation unit happens to pull in Polygon.hpp first. Under WASM the
#    include order differs and clang reports the cascade:
#
#      error: member access into incomplete type 'const ExPolygon'
#      error: arithmetic on a pointer to an incomplete type
#
#    Including Polygon.hpp directly is the correct fix either way: relying on
#    transitive includes is what makes this order-dependent.
def patch_clipperz_includes() -> None:
    patch("src/libslic3r/ClipperZUtils.hpp", [(
        '''#include <clipper/clipper_z.hpp>
#include <libslic3r/Point.hpp>''',
        '''#include <clipper/clipper_z.hpp>
#include <libslic3r/Point.hpp>
// The inline API below calls ExPolygon::num_contours and reads contour/holes, so
// the definition must be visible. It lives in ExPolygon.hpp -- Polygon.hpp does
// NOT define ExPolygon, which is what made the first attempt at this fix a no-op.
#include <libslic3r/ExPolygon.hpp>''',
        "ClipperZUtils ExPolygon include",
    )])


# 8b. Format/STEP.hpp -- OCCT headers are unconditional.
#
#     Model.hpp includes this header unconditionally, and the header immediately
#     pulls in five OpenCASCADE headers with no guard at all. With OCCT excluded
#     from the WASM build those files do not exist:
#
#       Format/STEP.hpp:3:10: fatal error: 'XCAFDoc_DocumentTool.hxx' file not found
#
#     Guard the OCCT-dependent portion. STEP import/export is a desktop-only
#     feature (it is reached through the GUI file dialogs), so on WASM the whole
#     translation unit reduces to an empty, includable header.
def patch_strip_step() -> None:
    patch("src/libslic3r/CMakeLists.txt", [(
        """    Format/STEP.cpp
    Format/STEP.hpp
""",
        """# Format/STEP.cpp and Format/STEP.hpp are OMITTED for WASM: they are the only
# files that include OpenCASCADE headers, and OCCT is not part of this build.
""",
        "drop STEP sources from the build",
    )])

    # Model.hpp: drop the include. Removing the sources from CMake is not
    # enough -- Model.hpp still #includes the header directly, so every
    # translation unit that pulls in Model.hpp ends up compiling it:
    #
    #   Model.hpp:25 -> Format/STEP.hpp:3: fatal error: XCAFDoc_DocumentTool.hxx
    #
    # This is the piece the earlier guard attempts were working around, and the
    # piece I dropped when replacing those attempts with a module removal.
    patch("src/libslic3r/Model.hpp", [(
        '#include "Format/STEP.hpp"',
        """// Format/STEP.hpp is not part of the WASM build (it is the only header that
// includes OpenCASCADE). The STEP entry points below are stubbed out in
// Model.cpp; keep the type names declared so the class layout is unchanged.
namespace Slic3r {
class Step;
// Must be a complete type, not a forward declaration: Model stores these in a
// std::vector, and instantiating that requires sizeof(StepImportTreeNode).
//   allocator.h:139: invalid application of sizeof to an incomplete type
struct StepImportTreeNode {
    std::wstring name;
    std::wstring uuid;
    std::wstring type;
    std::vector<StepImportTreeNode> children;
};
using StepIsUtf8Fn = std::function<bool(std::string const &)>;
using ImportStepProgressFn = std::function<void(int)>;
} // namespace Slic3r""",
        "Model.hpp: drop STEP include",
    )])

    # Model.cpp: remove Model::read_from_step in full.
    path = SRC / "src/libslic3r/Model.cpp"
    if not path.exists():
        _failures.append("Model.cpp missing")
        return
    text = path.read_text(encoding="utf-8")
    if "READ_FROM_STEP_REMOVED_FOR_WASM" in text:
        _log("  OK   Model.cpp  [read_from_step removed: already applied]")
        return
    start = text.find("Model Model::read_from_step(")
    if start < 0:
        _failures.append("Model.cpp: read_from_step not found")
        return
    # The function ends at the first closing brace at column 0 after 'start'.
    end = text.find("\n}\n", start)
    if end < 0:
        _failures.append("Model.cpp: read_from_step end not found")
        return
    end += len("\n}\n")
    stub = (
        "// READ_FROM_STEP_REMOVED_FOR_WASM\n"
        "// The OCCT-backed STEP importer is not compiled for WebAssembly.\n"
        "// Callers in the GUI never reach this on the web build.\n"
        "Model Model::read_from_step(const std::string &, LoadStrategy,\n"
        "                           ImportStepProgressFn, StepIsUtf8Fn,\n"
        "                           std::function<int(Slic3r::Step &, double &, double &, bool &)>,\n"
        "                           double, double, bool,\n"
        "                           std::function<void(const std::vector<std::string> &)>)\n"
        "{\n"
        "    throw std::runtime_error(\"STEP import is unavailable in the WebAssembly build\");\n"
        "}\n"
    )
    text = text[:start] + stub + text[end:]
    if DRY_RUN:
        _log("  WOULD STRIP Model.cpp  [read_from_step body]")
        return
    path.write_text(text, encoding="utf-8")
    _log("  STRIPPED Model.cpp  [read_from_step body]")


# 10. Strip the other two OCCT-dependent modules.
#
#     An audit finds exactly three consumers of OpenCASCADE:
#       Format/STEP.cpp   (37 refs) -- removed above
#       Format/svg.cpp    (37 refs) -- 3D extrusion of the imported outline
#       Shape/TextShape.cpp (33 refs) -- turns text into a solid via OCCT
#
#     svg.cpp keeps nanosvg for parsing and only reaches OCCT to extrude the
#     result into a mesh; TextShape.cpp exists solely to do that. Neither is
#     reachable from the headless slicing path, so both are dropped and their
#     entry points stubbed.
def patch_strip_occt_modules() -> None:
    patch("src/libslic3r/CMakeLists.txt", [(
        """    Format/svg.cpp
""",
        """# Format/svg.cpp is OMITTED for WASM: it extrudes the imported outline through
# OpenCASCADE. load_svg is stubbed below.
""",
        "drop svg.cpp from the build",
    )])

    # One patch, not two. Splitting "drop the source" and "register the stub"
    # into separate patch() calls makes them fight: the register step rewrites
    # the comment the drop step inserted, so on a second run the drop step can
    # no longer find its own replacement text and reports a missing anchor.
    # Emit the final shape in a single replacement.
    patch("src/libslic3r/CMakeLists.txt", [(
        """    Shape/TextShape.hpp
    Shape/TextShape.cpp
""",
        """    Shape/TextShape.hpp
# Shape/TextShape.cpp is OMITTED for WASM: it builds text solids with
# OpenCASCADE. This stub keeps text_to_mesh linkable.
    Shape/TextShape_wasm_stub.cpp
""",
        "drop TextShape.cpp, register its stub",
    )])

    # svg.hpp declares load_svg with a std::string& parameter but never includes
    # <string>. Desktop builds reach it through whatever the including file
    # pulled in first; the stub translation unit includes it standalone and
    # surfaces the omission:
    #   Format/svg.hpp:5:54: error: use of undeclared identifier 'std'
    patch("src/libslic3r/Format/svg.hpp", [(
        """#pragma once
namespace Slic3r {""",
        """#pragma once

#include <string>

namespace Slic3r {""",
        "svg.hpp: include <string>",
    )])

    # TextShape provides text_to_mesh; give it a throw-only replacement.
    stub = (
        "// Provided by patches/apply.py: Shape/TextShape.cpp is not built for WASM\n"
        "// (it converts text to solids through OpenCASCADE). Holds exactly the\n"
        "// declarations from TextShape.hpp; none of them is reachable from the\n"
        "// headless slicing path.\n"
        "#include \"TextShape.hpp\"\n"
        "\n"
        "namespace Slic3r {\n"
        "\n"
        "std::vector<std::string> init_occt_fonts() { return {}; }\n"
        "\n"
        "void load_text_shape(const char *, const char *, const float, const float,\n"
        "                     bool, bool, TextResult &)\n"
        "{}\n"
        "\n"
        "std::map<std::string, std::string> get_occt_fonts_maps() { return {}; }\n"
        "\n"
        "} // namespace Slic3r\n"
    )
    stub_path = SRC / "src/libslic3r/Shape/TextShape_wasm_stub.cpp"
    if stub_path.exists() and stub_path.read_text(encoding="utf-8") == stub:
        _log("  OK   Shape/TextShape_wasm_stub.cpp  [already present]")
    elif DRY_RUN:
        _log("  WOULD WRITE Shape/TextShape_wasm_stub.cpp")
    else:
        stub_path.write_text(stub, encoding="utf-8")
        _log("  WROTE Shape/TextShape_wasm_stub.cpp")

    # svg: load_svg is declared in Format/svg.hpp and called from Model.cpp.
    stub2 = (
        "// Provided by patches/apply.py: Format/svg.cpp is not built for WASM.\n"
        "#include \"svg.hpp\"\n"
        "\n"
        "#include <stdexcept>\n"
        "\n"
        "namespace Slic3r {\n"
        "\n"
        "bool load_svg(const char *, Model *, std::string &)\n"
        "{\n"
        "    throw std::runtime_error(\"SVG import is unavailable in the WebAssembly build\");\n"
        "}\n"
        "\n"
        "} // namespace Slic3r\n"
    )
    stub2_path = SRC / "src/libslic3r/Format/svg_wasm_stub.cpp"
    if stub2_path.exists() and stub2_path.read_text(encoding="utf-8") == stub2:
        _log("  OK   Format/svg_wasm_stub.cpp  [already present]")
    elif DRY_RUN:
        _log("  WOULD WRITE Format/svg_wasm_stub.cpp")
    else:
        stub2_path.write_text(stub2, encoding="utf-8")
        _log("  WROTE Format/svg_wasm_stub.cpp")

    # Register both stubs as sources.
    patch("src/libslic3r/CMakeLists.txt", [(
        """# OpenCASCADE. load_svg is stubbed below.
""",
        """# OpenCASCADE. load_svg is stubbed below.
    Format/svg_wasm_stub.cpp
""",
        "register svg stub",
    )])


# 11. Strip the OpenCV and assimp modules.
#
#     TexturePainting.cpp (929 lines) is OpenCV-based texture-to-painting
#     conversion; AssimpImport.cpp imports FBX/3DS through assimp. Neither sits
#     on the headless slicing path, and neither library can be cross-compiled
#     here in reasonable time, so both are dropped and stubbed.
#
#     The stubs keep the declared entry points linkable for the few call sites
#     that remain (Model.cpp:424 reaches load_assimp_textured_model only for
#     formats the headless build never loads).
def patch_strip_cv_assimp() -> None:
    patch("src/libslic3r/CMakeLists.txt", [(
        """    Format/AssimpImport.hpp
    Format/AssimpImport.cpp
""",
        """    Format/AssimpImport.hpp
# Format/AssimpImport.cpp is OMITTED for WASM: it needs assimp, a desktop-only
# import library. load_assimp_textured_model is stubbed.
    Format/AssimpImport_wasm_stub.cpp
""",
        "drop AssimpImport.cpp, register stub",
    )])

    patch("src/libslic3r/CMakeLists.txt", [(
        """    TexturePainting.hpp
    TexturePainting.cpp
""",
        """    TexturePainting.hpp
# TexturePainting.cpp is OMITTED for WASM: it needs OpenCV. Its declared entry
# points are stubbed.
    TexturePainting_wasm_stub.cpp
""",
        "drop TexturePainting.cpp, register stub",
    )])

    # ObjColorUtils is the last OpenCV consumer in the tree. Its .hpp pulls in
    # opencv2/opencv.hpp and exposes only its own namespace; nothing outside the
    # file references it (verified by grepping the tree for its entry points), so
    # it goes rather than being stubbed.
    patch("src/libslic3r/CMakeLists.txt", [(
        """    ObjColorUtils.cpp
    ObjColorUtils.hpp
""",
        """# ObjColorUtils is OMITTED for WASM: it is the only remaining OpenCV consumer
# and nothing outside the file calls into it.
""",
        "drop ObjColorUtils",
    )])

    # TextureToColor is the implementation behind TexturePainting and is reached
    # only from it. With TexturePainting gone, nothing else references
    # tex2color:: -- verified by grepping the whole tree -- so the directory goes
    # too rather than being stubbed piecemeal.
    patch("src/libslic3r/CMakeLists.txt", [(
        """    TextureToColor/TextureToColor.hpp
    TextureToColor/TextureToColor.cpp
    TextureToColor/ColorUtils.hpp
    TextureToColor/ColorUtils.cpp
""",
        """# The TextureToColor/ sources are OMITTED for WASM: they back TexturePainting,
# which needs OpenCV and is itself stripped below. Nothing else in the tree
# references tex2color::.
""",
        "drop TextureToColor sources",
    )])

    assimp_stub = (
        "// Provided by patches/apply.py: Format/AssimpImport.cpp is not built for\n"
        "// WASM. assimp is a desktop-only import library.\n"
        "#include \"AssimpImport.hpp\"\n"
        "\n"
        "#include \"../TexturePainting.hpp\"\n"
        "\n"
        "namespace Slic3r {\n"
        "\n"
        "bool load_assimp_textured_model(const std::string &, TexturedMesh &, std::string *)\n"
        "{\n"
        "    return false;\n"
        "}\n"
        "\n"
        "} // namespace Slic3r\n"
    )
    ap = SRC / "src/libslic3r/Format/AssimpImport_wasm_stub.cpp"
    if ap.exists() and ap.read_text(encoding="utf-8") == assimp_stub:
        _log("  OK   Format/AssimpImport_wasm_stub.cpp  [already present]")
    elif DRY_RUN:
        _log("  WOULD WRITE Format/AssimpImport_wasm_stub.cpp")
    else:
        ap.write_text(assimp_stub, encoding="utf-8")
        _log("  WROTE Format/AssimpImport_wasm_stub.cpp")

    # TexturePainting exposes a wide surface; emit the definitions it declares
    # and nothing else. The bodies are unreachable on this platform.
    tp_stub = (
        "// Provided by patches/apply.py: TexturePainting.cpp is not built for WASM\n"
        "// because it needs OpenCV. Every declared entry point is provided inert;\n"
        "// none of these is reachable from the headless slicing path.\n"
        "#include \"TexturePainting.hpp\"\n"
        "\n"
        "namespace Slic3r {\n"
        "\n"
        "// The deleter is declared in the header and normally defined in\n"
        "// TextureToColor.cpp, which is not built here. It cannot delete: the\n"
        "// pointee is only forward-declared in this configuration, and nothing\n"
        "// ever allocates one, so the pointer is always null.\n"
        "void MeshRepairCacheDeleter::operator()(tex2color::MeshRepairCache *) const {}\n"
        "\n"
        "MeshRepairCachePtr make_mesh_repair_cache() { return {}; }\n"
        "\n"
        "bool mesh_repair_cache_can_skip_input(const MeshRepairCachePtr &,\n"
        "                                      std::size_t,\n"
        "                                      const TexturePaintingSettings &)\n"
        "{ return false; }\n"
        "\n"
        "bool mesh_repair_cache_win10_failed(const MeshRepairCachePtr &) { return true; }\n"
        "\n"
        "bool copy_prepared_mesh_from_cache(const MeshRepairCachePtr &, PaintedMesh &)\n"
        "{ return false; }\n"
        "\n"
        "bool cluster_from_repair_cache(PaintedMesh &, const TexturePaintingSettings &,\n"
        "                               PaintProgressCallback, PaintCancelCallback)\n"
        "{ return false; }\n"
        "\n"
        "bool texture_to_painting(const TexturedMesh &, PaintedMesh &,\n"
        "                         const TexturePaintingSettings &,\n"
        "                         PaintProgressCallback, PaintCancelCallback)\n"
        "{ return false; }\n"
        "\n"
        "bool face_colors_to_painting(const TexturedMesh &, PaintedMesh &,\n"
        "                             const TexturePaintingSettings &,\n"
        "                             PaintProgressCallback, PaintCancelCallback)\n"
        "{ return false; }\n"
        "\n"
        "bool standard_3mf_colors_to_painting(const TexturedMesh &, PaintedMesh &,\n"
        "                                     const TexturePaintingSettings &,\n"
        "                                     PaintProgressCallback, PaintCancelCallback)\n"
        "{ return false; }\n"
        "\n"
        "std::vector<FilamentMatch> match_clusters_to_filaments(\n"
        "    const std::vector<std::array<std::size_t, 3>> &,\n"
        "    const std::vector<std::array<float, 4>> &,\n"
        "    const std::vector<std::string> &)\n"
        "{ return {}; }\n"
        "\n"
        "double compute_delta_e(const std::array<std::size_t, 3> &,\n"
        "                       const std::array<float, 4> &)\n"
        "{ return 0.0; }\n"
        "\n"
        "double compute_delta_e(const std::array<std::size_t, 3> &,\n"
        "                       const std::array<std::size_t, 3> &)\n"
        "{ return 0.0; }\n"
        "\n"
        "} // namespace Slic3r\n"
    )
    tp = SRC / "src/libslic3r/TexturePainting_wasm_stub.cpp"
    if tp.exists() and tp.read_text(encoding="utf-8") == tp_stub:
        _log("  OK   TexturePainting_wasm_stub.cpp  [already present]")
    elif DRY_RUN:
        _log("  WOULD WRITE TexturePainting_wasm_stub.cpp")
    else:
        tp.write_text(tp_stub, encoding="utf-8")
        _log("  WROTE TexturePainting_wasm_stub.cpp")


# 12. LocalesUtils.cpp -- <sstream> is only reachable on the Windows branch.
#
#     The file includes <charconv> under _WIN32 and uses std::stringstream in the
#     #else arm, without ever including <sstream>. Desktop builds get away with it
#     because some other header pulls sstream in; clang here reports:
#
#       LocalesUtils.cpp:81:23: error: implicit instantiation of undefined
#           template 'std::basic_stringstream<char>'
#
#     Include it unconditionally: both branches then have what they need and the
#     dependency is explicit.
def patch_locales_sstream() -> None:
    patch("src/libslic3r/LocalesUtils.cpp", [(
        """#include <stdexcept>""",
        """#include <sstream>
#include <stdexcept>""",
        "LocalesUtils: include <sstream>",
    )])


# 13. utils.cpp -- hard-wire the internal-testing switch.
#
#     The file uses `BBL_INTERNAL_TESTING == 1` in three ternaries. Defining the
#     macro on the command line should be enough, and locally it is: em++ with
#     -DBBL_INTERNAL_TESTING=0 expands the expression correctly and compiles.
#     In CI the same compile still fails at the same column with
#     "expected expression", which means the identifier is reaching the compiler
#     unexpanded there -- three rounds have now gone into trying to influence
#     that from CMake.
#
#     Stop depending on it. Replace the expression with a literal 0 in the
#     source, so the parse no longer involves the macro at all. Behaviour is
#     identical to BBL_INTERNAL_TESTING=0: the beta path is taken.
def patch_utils_internal_testing() -> None:
    with open(SRC / "src/libslic3r/utils.cpp", "rb") as fh:
        raw = fh.read().decode("utf-8")
    needle = "BBL_INTERNAL_TESTING == 1"
    if "0 == 1" in raw and needle not in raw:
        _log("  OK   utils.cpp  [internal-testing literal: already applied]")
        return
    n = raw.count(needle)
    if n == 0:
        _failures.append("utils.cpp: BBL_INTERNAL_TESTING expression not found")
        return
    raw = raw.replace(needle, "0 == 1")
    if DRY_RUN:
        _log(f"  WOULD REWRITE utils.cpp  [internal-testing literal x{n}]")
        return
    (SRC / "src/libslic3r/utils.cpp").write_text(raw, encoding="utf-8")
    _log(f"  REWROTE utils.cpp  [internal-testing literal x{n}]")


# 14. Strip the SLA (resin) subsystem and the last OpenVDB consumers.
#
#     OpenVDB has no WASM build and its dependency chain (Blosc, Imath, TBB
#     integration) is not worth porting for what it enables. Its real consumers
#     are all resin-printing features:
#
#       SLA/Hollowing.cpp        -- hollowing, SLA only
#       CSGMesh/VoxelizeCSGMesh  -- header-only, referenced by nothing
#       TreeSupport3D            -- its OpenVDB branch is disabled by
#                                   TREE_SUPPORT_ORGANIC_NUDGE_NEW=1
#
#     SLA is the resin slicer: 35 files, ~5200 lines, reachable only from
#     SLAPrintSteps/SLAPrint. FDM slicing never enters it. Model.hpp touches it
#     only through a forward declaration and friend entries, which stay valid
#     with the class never defined.
#
#     This is a real capability cut: resin hollowing and resin support
#     generation are gone from this build. Phase one accepted that trade to get
#     a working FDM engine.
def patch_strip_sla() -> None:
    cm = SRC / 'src/libslic3r/CMakeLists.txt'
    text = cm.read_text(encoding='utf-8')
    if 'SLA/ (resin) subsystem is OMITTED' in text:
        _log('  OK   src/libslic3r/CMakeLists.txt  [SLA sources: already removed]')
    else:
        lines = text.splitlines(keepends=True)
        kept, dropped = [], 0
        for ln in lines:
            st = ln.strip()
            if st.startswith('SLA/') and not st.startswith('SLA/SupportTreeIGL'):
                dropped += 1
                continue
            kept.append(ln)
        header = (
            '# The SLA/ (resin) subsystem is OMITTED for WASM. It is the resin slicer:\n'
            '# unreachable from FDM slicing, and the last consumer of OpenVDB, which\n'
            '# has no WebAssembly build. Resin hollowing and resin supports are\n'
            '# therefore unavailable in this build.\n'
        )
        out, inserted = [], False
        for ln in kept:
            if not inserted and ln.strip().startswith('Arachne/BeadingStrategy'):
                out.append(header)
                inserted = True
            out.append(ln)
        if DRY_RUN:
            _log(f'  WOULD REMOVE {dropped} SLA sources')
        else:
            cm.write_text(''.join(out), encoding='utf-8')
            _log(f'  REMOVED {dropped} SLA sources')

    # Keep the OpenVDBUtils translation unit out of the build regardless of the
    # upstream guard, which keys off a target that will never exist here.
    # The upstream line ends the add_library() argument list, so the closing
    # paren must survive: commenting out the whole line leaves
    # "Function missing ending \)". Keep the paren outside the comment.
    patch("src/libslic3r/CMakeLists.txt", [(
        "${OpenVDBUtils_SOURCES})",
        "# OpenVDB has no WASM build; the variable is empty.\n"
        "    )",
        "OpenVDBUtils excluded",
    )])


# 15. Guard OCCT_LIBS and drop the cereal library name.
#
#     Wrapping find_package(OpenCASCADE) stops the search but leaves two
#     downstream references live:
#       set(OCCT_LIBS TKXDESTEP TKSTEP ...)   -- link flag names
#       OCCT_LIBS on the target_link_libraries line
#     so wasm-ld reports "unable to find library -lTKXDESTEP" for each one.
#
#     cereal is header-only: its package exports an INTERFACE target and there is
#     no libcereal.a, so the bare name on the link line is a linker error.
def patch_link_lines() -> None:
    patch('src/libslic3r/CMakeLists.txt', [(
        'set(OCCT_LIBS\n    TKXDESTEP',
        'if(NOT SLIC3R_WASM)\nset(OCCT_LIBS\n    TKXDESTEP',
        'OCCT_LIBS guarded (open)',
    )])

    patch('src/libslic3r/CMakeLists.txt', [(
        'target_link_libraries(libslic3r\n    noise::noise\n    libnest2d\n    admesh\n    cereal',
        'endif()\n'
        '\n'
        'target_link_libraries(libslic3r\n    noise::noise\n    libnest2d\n    admesh\n'
        '    # cereal is header-only (INTERFACE target); naming it bare asks the\n'
        '    # linker for a libcereal.a that does not exist.\n'
        '    # cereal',
        'OCCT_LIBS guarded (close), cereal dropped',
    )])

    patch('src/libslic3r/CMakeLists.txt', [(
        '    ' + D + '{OCCT_LIBS}\n',
        '    # ' + D + '{OCCT_LIBS} -- OCCT is not in the WASM build\n',
        'OCCT_LIBS dropped from link line',
    )])


# 16. Guard the Freetype/fontconfig link block.
#
#     Under WASM the block still runs (NOT WIN32 is true) and links two
#     desktop-only text libraries:
#       find_package(Freetype REQUIRED)
#       target_link_libraries(libslic3r fontconfig)
#     wasm-ld then fails on -lfontconfig. Text rendering is a GUI concern and the
#     headless kernel never reaches it, so the whole block is skipped.
def patch_freetype_guard() -> None:
    patch('src/libslic3r/CMakeLists.txt', [(
        '    find_package(Freetype REQUIRED)',
        '    if(NOT SLIC3R_WASM)\n    find_package(Freetype REQUIRED)',
        'Freetype block guarded (open)',
    )])
    patch('src/libslic3r/CMakeLists.txt', [(
        '        target_link_libraries(libslic3r fontconfig)\n    endif()',
        '        target_link_libraries(libslic3r fontconfig)\n    endif()\n    endif()',
        'Freetype block guarded (close)',
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
        ("[7] ClipperZUtils include fix", patch_clipperz_includes),
        ("[9] strip the OCCT STEP importer", patch_strip_step),
        ("[10] strip svg and TextShape", patch_strip_occt_modules),
        ("[11] strip OpenCV and assimp modules", patch_strip_cv_assimp),
        ("[12] LocalesUtils <sstream>", patch_locales_sstream),
        ("[13] utils.cpp internal-testing literal", patch_utils_internal_testing),
        ("[14] strip SLA and OpenVDB", patch_strip_sla),
        ("[15] guard OCCT_LIBS, drop cereal", patch_link_lines),
        ("[16] guard freetype/fontconfig", patch_freetype_guard),
        ("[17] bridge injection", patch_bridge),
    ]:
        _log(step)
        fn()

    # Structural check: the CMakeList edits are line-surgery and can silently
    # leave a function unclosed, which CMake only reports as
    # "Function missing ending )" with no pointer to the edit that caused it.
    # Balance the parens here instead.
    for rel in ("src/libslic3r/CMakeLists.txt", "CMakeLists.txt"):
        f = SRC / rel
        if not f.exists():
            continue
        t = f.read_text(encoding="utf-8")
        # Ignore comments: a paren inside a comment does not count for CMake.
        stripped = "\n".join(
            line for line in t.splitlines() if not line.lstrip().startswith("#")
        )
        if stripped.count("(") != stripped.count(")"):
            _failures.append(
                f"{rel}: unbalanced parentheses ({stripped.count('(')} open vs "
                f"{stripped.count(')')} close) -- a patch likely commented out a closing paren"
            )

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
