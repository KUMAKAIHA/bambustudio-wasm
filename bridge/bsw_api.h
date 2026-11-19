/* bambustudio-wasm -- C ABI
 *
 * The JavaScript host never touches the WASM heap directly; every call goes
 * through these functions. Strings cross the boundary as UTF-8 in MEMFS files
 * or as caller-supplied buffers, never as C++ std::string -- the Emscripten
 * ABI cannot marshal those and the mismatch crashes silently.
 *
 * Every function returning int returns 0 on success, negative on failure.
 * bsw_last_error() gives a human-readable reason after a failure.
 */
#ifndef BAMBU_WASM_API_H
#define BAMBU_WASM_API_H

#ifdef __cplusplus
extern "C" {
#endif

#define BSW_OK                0
#define BSW_ERR_STATE        -1
#define BSW_ERR_JSON         -2
#define BSW_ERR_IO           -3
#define BSW_ERR_LOAD         -4
#define BSW_ERR_EMPTY        -5
#define BSW_ERR_VALIDATE     -6
#define BSW_ERR_SLICE        -7
#define BSW_ERR_EXPORT       -8
#define BSW_ERR_EXCEPTION    -9
#define BSW_ERR_CANCELLED   -11
#define BSW_ERR_UNAVAILABLE -12

void *bsw_session_create(void);
void  bsw_session_destroy(void *session);
int   bsw_init(void *session, const char *config_json);

int bsw_model_load(void *session, const char *memfs_path, const char *format_hint);
int bsw_model_export_stl(void *session, const char *out_memfs_path);
int bsw_model_transform(void *session, const char *transform_json);
int bsw_model_orient(void *session);
int bsw_model_arrange(void *session);
int bsw_model_info(void *session, char *out, int out_len);

int  bsw_slice(void *session, const char *out_gcode_memfs_path);
void bsw_cancel(void *session);

typedef void (*bsw_progress_fn)(int percent, const char *stage, void *user_data);
void bsw_set_progress_callback(void *session, bsw_progress_fn fn, void *user_data);

int bsw_asset_size(void *session, const char *memfs_path);
int bsw_asset_read(void *session, const char *memfs_path, char *out, int out_len);

const char *bsw_last_error(void *session);
const char *bsw_capabilities(void);
void        bsw_free(void *ptr);

#ifdef __cplusplus
}
#endif
#endif
