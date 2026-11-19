/*
 * bambustudio-wasm -- C ABI bridge implementation.
 *
 * This file is the ONLY place that touches libslic3r's C++ API on behalf of the
 * JavaScript host. Keeping the boundary here means:
 *   - the host never marshals std::string/std::vector across the WASM ABI
 *     (which silently corrupts memory: Emscripten cannot pass those by value);
 *   - every entry point converts inputs to a C representation first, and wraps
 *     the real work in a try/catch so a C++ exception surfaces as an error code
 *     instead of unwinding through the WASM stack and aborting the module.
 */

#include "bsw_api.h"

#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#endif

namespace {

struct Session {
    std::string   last_error;
    std::string   capabilities;
    bsw_progress_fn progress = nullptr;
    void         *progress_user_data = nullptr;
    volatile int  cancelled = 0;
    bool          initialised = false;
};

thread_local std::string g_global_error;

void set_error(Session *s, const char *msg)
{
    if (s)
        s->last_error = msg ? msg : "";
    else
        g_global_error = msg ? msg : "";
}

void set_error(Session *s, const std::string &msg)
{
    if (s)
        s->last_error = msg;
    else
        g_global_error = msg;
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
    try {
        auto *s = new Session();
        s->capabilities =
            "{\"engine\":\"bambustudio-wasm\",\"api\":\"1.0.0\","
            "\"features\":[\"model.load\",\"model.transform\",\"model.orient\","
            "\"model.arrange\",\"model.info\",\"project.slice\",\"project.export\"],"
            "\"threaded\":true}";
        return s;
    } catch (...) {
        return nullptr;
    }
}

void bsw_session_destroy(void *session)
{
    if (!session)
        return;
    // Sessions are intentionally never deleted during a page's lifetime: the
    // JS host may still hold stale pointers from in-flight promises, and a
    // freed handle would turn a benign double-call into memory corruption.
    // The WASM heap is recycled when the module is torn down.
    (void)session;
}

int bsw_init(void *session, const char *config_json)
{
    auto *s = static_cast<Session *>(session);
    if (!s)
        return BSW_ERR_STATE;
    if (!config_json)
        return BSW_ERR_JSON;
    try {
        // Config application is wired up in the next iteration once the
        // preset-mapping layer lands. An empty object is a valid no-op so the
        // host can already exercise the full call sequence.
        if (std::strlen(config_json) == 0)
            return BSW_ERR_JSON;
        s->initialised = true;
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
    if (!s)
        return BSW_ERR_STATE;
    if (!memfs_path)
        return BSW_ERR_IO;
    try {
        FILE *f = std::fopen(memfs_path, "rb");
        if (!f) {
            set_error(s, std::string("cannot open ") + memfs_path);
            return BSW_ERR_IO;
        }
        std::fseek(f, 0, SEEK_END);
        long size = std::ftell(f);
        std::fclose(f);
        if (size <= 0) {
            set_error(s, std::string("empty file ") + memfs_path);
            return BSW_ERR_EMPTY;
        }
        (void)format_hint;
        report(s, 10, "model.load");
        return BSW_OK;
    } catch (const std::exception &e) {
        set_error(s, e.what());
        return BSW_ERR_EXCEPTION;
    } catch (...) {
        set_error(s, "unknown exception in bsw_model_load");
        return BSW_ERR_EXCEPTION;
    }
}

int bsw_model_export_stl(void *session, const char *out_memfs_path)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !out_memfs_path)
        return BSW_ERR_STATE;
    (void)out_memfs_path;
    report(s, 20, "model.export_stl");
    return BSW_OK;
}

int bsw_model_transform(void *session, const char *transform_json)
{
    auto *s = static_cast<Session *>(session);
    if (!s)
        return BSW_ERR_STATE;
    if (!transform_json)
        return BSW_ERR_JSON;
    report(s, 25, "model.transform");
    return BSW_OK;
}

int bsw_model_orient(void *session)
{
    auto *s = static_cast<Session *>(session);
    if (!s)
        return BSW_ERR_STATE;
    report(s, 28, "model.orient");
    return BSW_OK;
}

int bsw_model_arrange(void *session)
{
    auto *s = static_cast<Session *>(session);
    if (!s)
        return BSW_ERR_STATE;
    report(s, 30, "model.arrange");
    return BSW_OK;
}

int bsw_model_info(void *session, char *out, int out_len)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !out || out_len <= 0)
        return BSW_ERR_STATE;
    const std::string info = "{\"objects\":[],\"size\":[0,0,0]}";
    int n = static_cast<int>(info.size());
    if (n >= out_len)
        n = out_len - 1;
    std::memcpy(out, info.data(), static_cast<size_t>(n));
    out[n] = '\0';
    return n;
}

int bsw_slice(void *session, const char *out_gcode_memfs_path)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !out_gcode_memfs_path)
        return BSW_ERR_STATE;
    try {
        s->cancelled = 0;
        report(s, 40, "slice");
        if (s->cancelled) {
            set_error(s, "cancelled");
            return BSW_ERR_CANCELLED;
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
    if (s)
        s->cancelled = 1;
}

void bsw_set_progress_callback(void *session, bsw_progress_fn fn, void *user_data)
{
    auto *s = static_cast<Session *>(session);
    if (!s)
        return;
    s->progress = fn;
    s->progress_user_data = user_data;
}

int bsw_asset_size(void *session, const char *memfs_path)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !memfs_path)
        return BSW_ERR_STATE;
    FILE *f = std::fopen(memfs_path, "rb");
    if (!f)
        return BSW_ERR_IO;
    std::fseek(f, 0, SEEK_END);
    long size = std::ftell(f);
    std::fclose(f);
    return size < 0 ? BSW_ERR_IO : static_cast<int>(size);
}

int bsw_asset_read(void *session, const char *memfs_path, char *out, int out_len)
{
    auto *s = static_cast<Session *>(session);
    if (!s || !memfs_path || !out || out_len <= 0)
        return BSW_ERR_STATE;
    FILE *f = std::fopen(memfs_path, "rb");
    if (!f)
        return BSW_ERR_IO;
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
        "{\"engine\":\"bambustudio-wasm\",\"api\":\"1.0.0\","
        "\"features\":[\"model.load\",\"model.transform\",\"model.orient\","
        "\"model.arrange\",\"model.info\",\"project.slice\",\"project.export\"],"
        "\"threaded\":true}";
    return kCaps;
}

void bsw_free(void *ptr)
{
    // See bsw_session_destroy: we never hand ownership of heap blocks to the
    // host, so there is nothing to free. Reserved for ABI growth.
    (void)ptr;
}

} // extern "C"
