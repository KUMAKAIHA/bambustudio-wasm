/**
 * BambuStudio WASM host.
 *
 * Loads the compiled engine and exposes it as a plain async API. Nothing here
 * knows about slicing internals -- it marshals calls across the C ABI and
 * surfaces progress, cancellation and errors.
 *
 * The module ships brotli-compressed because Cloudflare Pages caps a single
 * asset at 25 MiB and the raw .wasm exceeds that. Decompressing in the
 * browser with DecompressionStream is what a CDN would do anyway; we just
 * move the step earlier so the size limit stops mattering.
 */

const ENGINE_JS = '/assets/bambu-slicer.js';
const ENGINE_WASM_BR = '/assets/bambu-slicer.wasm.br';

let _module = null;
let _session = 0;

/**
 * Decompress a .br asset and compile it to a WebAssembly.Module.
 *
 * Emscripten's glue normally fetches the .wasm itself. We bypass that by
 * handing it a pre-compiled module through the instantiateWasm hook, so the
 * glue never touches the network and never needs an uncompressed file.
 */
async function loadWasmModule(url) {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error(
      'This browser lacks DecompressionStream (needs Chrome 80+, Firefox 113+, ' +
      'Safari 16.4+). The engine ships brotli-compressed to stay under the CDN ' +
      'single-asset size limit.'
    );
  }

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Engine asset unavailable: ' + url + ' (' + res.status + ')');
  }

  const stream = res.body.pipeThrough(new DecompressionStream('brotli'));
  const buf = await new Response(stream).arrayBuffer();
  return WebAssembly.compile(buf);
}

function getLastError() {
  if (!_module) return 'engine not loaded';
  const ptr = _module._bsw_last_error(_session || 0);
  return ptr ? _module.UTF8ToString(ptr) : 'unknown error';
}

/**
 * Boot the engine. Resolves once the module is instantiated and a session
 * exists.
 */
export async function createEngine(options) {
  const opts = options || {};
  const wasmModule = await loadWasmModule(ENGINE_WASM_BR);

  await new Promise(function (resolve, reject) {
    const s = document.createElement('script');
    s.src = ENGINE_JS;
    s.onload = resolve;
    s.onerror = function () {
      reject(new Error('Failed to load engine glue: ' + ENGINE_JS));
    };
    document.head.appendChild(s);
  });

  if (typeof window.BambuModule !== 'function') {
    throw new Error('Engine glue did not define BambuModule');
  }

  _module = await window.BambuModule({
    // Hand Emscripten the already-compiled module so it never fetches .wasm.
    instantiateWasm: function (imports, successCallback) {
      WebAssembly.instantiate(wasmModule, imports).then(function (instance) {
        successCallback(instance, wasmModule);
      });
      return {};
    },
    locateFile: function (path) { return '/assets/' + path; },
    print: function (msg) { console.debug('[engine]', msg); },
    printErr: function (msg) { console.warn('[engine]', msg); },
  });

  _session = _module._bsw_session_create();
  if (!_session) {
    throw new Error('Engine refused to create a session: ' + getLastError());
  }

  return new BambuEngine(_module, _session, opts.onProgress);
}

export class BambuEngine {
  constructor(mod, session, onProgress) {
    this.mod = mod;
    this.session = session;
    this.onProgress = onProgress || null;
    this._progressFn = null;
    this._installProgress();
  }

  _installProgress() {
    if (!this.onProgress) return;
    const self = this;
    // Emscripten function pointers are table indices; the stage string is a
    // pointer into the WASM heap and must be read before the callback returns.
    this._progressFn = this.mod.addFunction(function (pct, stagePtr) {
      const stage = self.mod.UTF8ToString(stagePtr);
      try {
        self.onProgress(pct, stage);
      } catch (e) {
        console.warn('[engine] progress handler threw', e);
      }
    }, 'vii');
    this.mod._bsw_set_progress_callback(this.session, this._progressFn, 0);
  }

  capabilities() {
    const ptr = this.mod._bsw_capabilities();
    return JSON.parse(this.mod.UTF8ToString(ptr));
  }

  /** Write a JS string into the WASM heap and run fn with the pointer. */
  _withString(str, fn) {
    const bytes = new TextEncoder().encode(str);
    const ptr = this.mod._malloc(bytes.length + 1);
    this.mod.HEAPU8.set(bytes, ptr);
    this.mod.HEAPU8[ptr + bytes.length] = 0;
    try {
      return fn(ptr);
    } finally {
      this.mod._free(ptr);
    }
  }

  _check(rc) {
    if (rc < 0) throw new Error(getLastError());
    return rc;
  }

  init(configJson) {
    const self = this;
    this._check(this._withString(configJson, function (p) {
      return self.mod._bsw_init(self.session, p);
    }));
  }

  loadModel(memfsPath, formatHint) {
    const self = this;
    this._check(this._withString(memfsPath, function (p) {
      return self._withString(formatHint || '', function (h) {
        return self.mod._bsw_model_load(self.session, p, h);
      });
    }));
  }

  /** Copy a File into MEMFS, then load it. */
  async loadFile(file, memfsPath) {
    const buf = new Uint8Array(await file.arrayBuffer());
    this.mod.FS.writeFile(memfsPath, buf);
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    this.loadModel(memfsPath, ext);
    return memfsPath;
  }

  transform(t) {
    const self = this;
    this._check(this._withString(JSON.stringify(t), function (p) {
      return self.mod._bsw_model_transform(self.session, p);
    }));
  }

  orient() { this._check(this.mod._bsw_model_orient(this.session)); }
  arrange() { this._check(this.mod._bsw_model_arrange(this.session)); }

  info() {
    const cap = 64 * 1024;
    const ptr = this.mod._malloc(cap);
    try {
      const n = this.mod._bsw_model_info(this.session, ptr, cap);
      if (n < 0) throw new Error(getLastError());
      return JSON.parse(this.mod.UTF8ToString(ptr));
    } finally {
      this.mod._free(ptr);
    }
  }

  slice(outPath) {
    const self = this;
    this._check(this._withString(outPath, function (p) {
      return self.mod._bsw_slice(self.session, p);
    }));
  }

  cancel() { this.mod._bsw_cancel(this.session); }

  /** Read a produced file back out of MEMFS as a Uint8Array. */
  readAsset(memfsPath) {
    const self = this;
    const size = this._withString(memfsPath, function (p) {
      return self.mod._bsw_asset_size(self.session, p);
    });
    this._check(size);
    const ptr = this.mod._malloc(size);
    try {
      const n = this._withString(memfsPath, function (p) {
        return self.mod._bsw_asset_read(self.session, p, ptr, size);
      });
      this._check(n);
      return new Uint8Array(this.mod.HEAPU8.subarray(ptr, ptr + n)).slice();
    } finally {
      this.mod._free(ptr);
    }
  }
}

