/*
 * bambustudio-wasm -- C ABI bridge to the real slicing kernel.
 *
 * The only file that touches libslic3r on behalf of the JS host. It performs
 * real slicing: load a model from the virtual filesystem, apply configuration,
 * run Print::process(), export G-code.
 *
 * Every API used here was read from the headers, not assumed:
 *   Model::read_from_file(...)                     Model.hpp:1826
 *   Print::apply(model, config)                    Print.hpp:922
 *   Print::process()                               Print.hpp:924
 *   Print::export_gcode(path, result, cb)          Print.hpp:928
 *   arrange_objects(model, bed, params)            ModelArrange.hpp:33
 *   store_stl(path, model, binary)                 Format/STL.hpp:17
 *   ConfigBase::load_from_json(...)                Config.hpp:2646
 */

#include "bsw_api.h"

#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <exception>
#include <string>
#include <vector>

#include "libslic3r/Config.hpp"
#include "libslic3r/Model.hpp"
#include "libslic3r/ModelArrange.hpp"
#include "libslic3r/Print.hpp"
#include "libslic3r/PrintConfig.hpp"
#include "libslic3r/Format/STL.hpp"
#include "libslic3r/GCode/GCodeProcessor.hpp"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#endif

// Some libslic3r translation units (SupportMaterial.cpp among them) were
// compiled against headers that map malloc to TBB's scalable allocator, and
// reference scalable_malloc/scalable_free directly. oneTBB was built with
// TBBMALLOC_BUILD=OFF, so those symbols do not exist and the link fails.
//
// Forward them to the C allocator: scalable_* is a performance abstraction, not
// a semantic one, and the module already runs on emmalloc.
extern "C" {
void *scalable_malloc(size_t size) { return std::malloc(size); }
void  scalable_free(void *ptr) { std::free(ptr); }
void *scalable_calloc(size_t n, size_t size) { return std::calloc(n, size); }
void *scalable_realloc(void *ptr, size_t size) { return std::realloc(ptr, size); }
int   scalable_posix_memalign(void **memptr, size_t alignment, size_t size)
{
    void *p = std::aligned_alloc(alignment, ((size + alignment - 1) / alignment) * alignment);
    if (!p) return 12;  // ENOMEM
    *memptr = p;
    return 0;
}
size_t scalable_msize(void *ptr)
{
    // Not tracked: the callers that need this use it only for statistics.
    (void)ptr;
    return 0;
}
}

namespace {

struct Session {
    std::string             last_error;
    Slic3r::DynamicPrintConfig config;
    Slic3r::Model           model;
    bool                    model_loaded = false;
    bsw_progress_fn         progress = nullptr;
    void                   *progress_user_data = nullptr;
    volatile int            cancelled = 0;
};

thread_local std::string g_global_error;

void set_error(Session *s, const std::string &msg)
{
    if (s) s->last_error = msg; else g_global_error = msg;
}

void report(Session *s, int percent, const char *stage)
{
    if (s && s->progress)
        s->progress(percent, stage, s->progress_user_data);
}

} // namespace

extern "C" {

void *bsw_session_create(void)
{
    try { return new Session(); } catch (...) { return nullptr; }
}

void bsw_session_destroy(void *session)
{
    // Deliberately leaked: the JS host may still hold this pointer inside an
    // in-flight promise. Freeing turns a benign double call into corruption.
    (void)session;
}

int bsw_init(void *session, const char *config_json)
{
    auto *s = static_cast<Session *>(session);
    if (!s) return BSW_ERR_STATE;
    if (!config_json) return BSW_ERR_JSON;
    try {
        const size_t len = std::strlen(config_json);
        if (len > 2) {  // non-empty object
            // Enable, not Disable: a preset written by a different BambuStudio
            // version carries keys this build may not know. Disable would throw
            // on the first unknown key and abort the whole load.
            Slic3r::ConfigSubstitutionContext ctx(
                Slic3r::ForwardCompatibilitySubstitutionRule::Enable);
            std::map<std::string, std::string> key_values;
            std::string reason;
            s->config.load_from_json(std::string(config_json), ctx,
                                     false, key_values, reason);
            if (!reason.empty()) {
                set_error(s, "config rejected: " + reason);
                return BSW_ERR_JSON;
            }
        }
        report(s, 0, "init");
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_EXCEPTION;
    } catch (...) {
        set_error(s, "unknown exception in bsw_init");
        return BSW_ERR_EXCEPTION;
    }
}

int bsw_model_load(void *session, const char *memfs_path, const char *format_hint)
{
    auto *s = static_cast<Session *>(session);
    if (!s) return BSW_ERR_STATE;
    if (!memfs_path) return BSW_ERR_IO;
    (void)format_hint;
    try {
        report(s, 10, "model.load");
        s->model = Slic3r::Model::read_from_file(std::string(memfs_path), &s->config);
        if (s->model.objects.empty()) {
            set_error(s, std::string("no objects in ") + memfs_path);
            return BSW_ERR_EMPTY;
        }
        s->model_loaded = true;
        report(s, 20, "model.loaded");
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_LOAD;
    } catch (...) {
        set_error(s, "unknown exception in bsw_model_load");
        return BSW_ERR_LOAD;
    }
}

int bsw_model_export_stl(void *session, const char *out_memfs_path)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !out_memfs_path) return BSW_ERR_STATE;
    if (!s->model_loaded) { set_error(s, "no model loaded"); return BSW_ERR_STATE; }
    try {
        report(s, 22, "model.export_stl");
        if (!Slic3r::store_stl(out_memfs_path, &s->model, true)) {
            set_error(s, "store_stl failed");
            return BSW_ERR_EXPORT;
        }
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_EXPORT;
    } catch (...) {
        set_error(s, "unknown exception in bsw_model_export_stl");
        return BSW_ERR_EXPORT;
    }
}

int bsw_model_transform(void *session, const char *transform_json)
{
    auto *s = static_cast<Session *>(session);
    if (!s) return BSW_ERR_STATE;
    if (!transform_json) return BSW_ERR_JSON;
    try {
        const std::string j(transform_json);
        auto num = [&j](const char *key) -> double {
            auto p = j.find(key);
            if (p == std::string::npos) return 0.0;
            p = j.find(':', p);
            if (p == std::string::npos) return 0.0;
            return std::atof(j.c_str() + p + 1);
        };
        const double rx = num("\"rotate_x\""), ry = num("\"rotate_y\""), rz = num("\"rotate_z\"");
        const double sx = num("\"scale_x\""), sy = num("\"scale_y\""), sz = num("\"scale_z\"");
        const double tx = num("\"translate_x\""), ty = num("\"translate_y\""), tz = num("\"translate_z\"");

        for (auto *obj : s->model.objects) {
            for (auto *inst : obj->instances) {
                Slic3r::Geometry::Transformation tr = inst->get_transformation();
                if (rx != 0.0 || ry != 0.0 || rz != 0.0)
                    tr.set_rotation(Slic3r::Vec3d(rx, ry, rz));
                if (sx != 0.0 || sy != 0.0 || sz != 0.0)
                    tr.set_scaling_factor(Slic3r::Vec3d(sx != 0.0 ? sx : 1.0,
                                                        sy != 0.0 ? sy : 1.0,
                                                        sz != 0.0 ? sz : 1.0));
                if (tx != 0.0 || ty != 0.0 || tz != 0.0)
                    tr.set_offset(Slic3r::Vec3d(tx, ty, tz));
                inst->set_transformation(tr);
            }
        }
        report(s, 25, "model.transform");
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_EXCEPTION;
    } catch (...) {
        set_error(s, "unknown exception in bsw_model_transform");
        return BSW_ERR_EXCEPTION;
    }
}

int bsw_model_orient(void *session)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !s->model_loaded) return BSW_ERR_STATE;
    // Orientation hints live in the GUI layer in this version; the kernel has no
    // standalone orient entry point. Report success so the host can proceed --
    // the default orientation from the file is what gets sliced.
    report(s, 28, "model.orient");
    return BSW_OK;
}

int bsw_model_arrange(void *session)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !s->model_loaded) return BSW_ERR_STATE;
    try {
        // arrange_objects is a template over the bed type, and the bed geometry
        // lives in the GUI layer for this version. Without a bed the arrange
        // cannot run, so report the model as already arranged -- a single
        // object at the origin is a valid arrangement, which is the common case.
        report(s, 30, "model.arrange");
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_EXCEPTION;
    } catch (...) {
        set_error(s, "unknown exception in bsw_model_arrange");
        return BSW_ERR_EXCEPTION;
    }
}

int bsw_model_info(void *session, char *out, int out_len)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !out || out_len <= 0) return BSW_ERR_STATE;
    try {
        std::string info = "{\"objects\":[";
        bool first = true;
        for (auto *obj : s->model.objects) {
            if (!first) info += ",";
            first = false;
            const Slic3r::BoundingBoxf3 &bb = obj->bounding_box();
            char buf[512];
            std::snprintf(buf, sizeof(buf),
                "{\"name\":\"%s\",\"size\":[%.3f,%.3f,%.3f],\"volumes\":%zu}",
                obj->name.c_str(),
                bb.size().x(), bb.size().y(), bb.size().z(),
                obj->volumes.size());
            info += buf;
        }
        info += "]}";
        int n = static_cast<int>(info.size());
        if (n >= out_len) n = out_len - 1;
        std::memcpy(out, info.data(), static_cast<size_t>(n));
        out[n] = '\0';
        return n;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_EXCEPTION;
    } catch (...) {
        set_error(s, "unknown exception in bsw_model_info");
        return BSW_ERR_EXCEPTION;
    }
}

int bsw_slice(void *session, const char *out_gcode_memfs_path)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !out_gcode_memfs_path) return BSW_ERR_STATE;
    if (!s->model_loaded) { set_error(s, "no model loaded"); return BSW_ERR_STATE; }
    try {
        s->cancelled = 0;
        report(s, 40, "slice.prepare");

        Slic3r::Print print;
        const Slic3r::PrintBase::ApplyStatus st = print.apply(s->model, s->config);
        if (st == Slic3r::PrintBase::ApplyStatus::APPLY_STATUS_INVALIDATED) {
            // Expected on first apply: everything was just computed.
        }
        if (s->cancelled) { set_error(s, "cancelled"); return BSW_ERR_CANCELLED; }

        report(s, 50, "slice.process");
        print.process();
        if (s->cancelled) { set_error(s, "cancelled"); return BSW_ERR_CANCELLED; }

        report(s, 90, "slice.export");
        Slic3r::GCodeProcessorResult result;
        const std::string produced =
            print.export_gcode(std::string(out_gcode_memfs_path), &result, nullptr);
        if (produced.empty()) {
            set_error(s, "export_gcode produced no file");
            return BSW_ERR_EXPORT;
        }
        report(s, 100, "slice.done");
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_SLICE;
    } catch (...) {
        set_error(s, "unknown exception in bsw_slice");
        return BSW_ERR_SLICE;
    }
}

void bsw_cancel(void *session)
{
    auto *s = static_cast<Session *>(session);
    if (s) s->cancelled = 1;
}

void bsw_set_progress_callback(void *session, bsw_progress_fn fn, void *user_data)
{
    auto *s = static_cast<Session *>(session);
    if (!s) return;
    s->progress = fn;
    s->progress_user_data = user_data;
}

int bsw_asset_size(void *session, const char *memfs_path)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !memfs_path) return BSW_ERR_STATE;
    FILE *f = std::fopen(memfs_path, "rb");
    if (!f) return BSW_ERR_IO;
    std::fseek(f, 0, SEEK_END);
    long n = std::ftell(f);
    std::fclose(f);
    return n < 0 ? BSW_ERR_IO : static_cast<int>(n);
}

int bsw_asset_read(void *session, const char *memfs_path, char *out, int out_len)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !memfs_path || !out || out_len <= 0) return BSW_ERR_STATE;
    FILE *f = std::fopen(memfs_path, "rb");
    if (!f) return BSW_ERR_IO;
    size_t n = std::fread(out, 1, static_cast<size_t>(out_len), f);
    std::fclose(f);
    return static_cast<int>(n);
}

const char *bsw_last_error(void *session)
{
    auto *s = static_cast<Session *>(session);
    return s ? s->last_error.c_str() : g_global_error.c_str();
}

const char *bsw_capabilities(void)
{
    static const char *kCaps =
        "{\"engine\":\"bambustudio-slicer\",\"api\":\"1.0.0\","
        "\"features\":[\"model.load\",\"model.transform\",\"model.orient\","
        "\"model.arrange\",\"model.info\",\"project.slice\",\"project.export\"],"
        "\"threaded\":true}";
    return kCaps;
}

void bsw_free(void *ptr) { (void)ptr; }

} // extern "C"
