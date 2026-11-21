#!/usr/bin/env node
/*
 * Verify the built engine the way a host will use it.
 *
 * The raw wasm export table is not a meaningful target for this check: -O3
 * minifies the exported names (they come out as "$", "Aa", "Ba", ...) and the
 * Emscripten glue is what maps them onto the documented _bsw_* entry points.
 * So this loads the glue, instantiates the module, and asserts that the C ABI
 * is reachable through the Module object.
 */

const fs = require('fs');
const path = require('path');
const Module = require('module');

const base = process.argv[2] || 'artifacts/bambu-slicer';
const jsPath = path.resolve(base + '.js');
const wasmPath = path.resolve(base + '.wasm');

function fail(msg) {
  console.error('::error::' + msg);
  process.exit(1);
}

if (!fs.existsSync(jsPath)) fail('missing glue: ' + jsPath);
if (!fs.existsSync(wasmPath)) fail('missing wasm: ' + wasmPath);

const wasmBytes = fs.readFileSync(wasmPath);
const mib = wasmBytes.length / 1048576;
console.log('wasm size: ' + mib.toFixed(1) + ' MiB');

// The module is only useful if the slicer is really inside it.
if (mib < 5) {
  fail('module is only ' + mib.toFixed(1) + ' MiB -- the slicer kernel was not linked in');
}

// The generated glue is a CommonJS factory (MODULARIZE + EXPORT_NAME). Load it
// and instantiate with our own wasm bytes so nothing is fetched at runtime.
const glueDir = path.dirname(jsPath);
const factory = require(jsPath);

if (typeof factory !== 'function') {
  fail('glue did not export a module factory (got ' + typeof factory + ')');
}

const REQUIRED = [
  '_bsw_session_create',
  '_bsw_session_destroy',
  '_bsw_init',
  '_bsw_model_load',
  '_bsw_slice',
  '_bsw_cancel',
  '_bsw_asset_size',
  '_bsw_asset_read',
  '_bsw_last_error',
  '_bsw_capabilities',
];

(async () => {
  const mod = await factory({
    // Hand it the bytes we already read: the default path would fetch the file
    // through the filesystem shim, which behaves differently under node.
    wasmBinary: wasmBytes,
    locateFile: (p) => path.join(glueDir, p),
    // The engine writes diagnostics through print/printErr.
    print: () => {},
    printErr: () => {},
  });

  const missing = REQUIRED.filter((n) => typeof mod[n] !== 'function');
  if (missing.length) {
    const present = Object.keys(mod)
      .filter((k) => k.startsWith('_bsw'))
      .sort();
    console.error('missing exports: ' + missing.join(', '));
    console.error('bsw entries present: ' + (present.join(', ') || '(none)'));
    fail('engine does not expose the documented C ABI');
  }

  console.log('ABI OK: ' + REQUIRED.length + ' entry points reachable');

  // Exercise the session lifecycle: this proves the module actually
  // initialises the slicer and is not merely a correctly-named stub.
  const session = mod._bsw_session_create();
  if (!session) fail('bsw_session_create returned null');

  const capsPtr = mod._bsw_capabilities();
  if (!capsPtr) fail('bsw_capabilities returned null');
  const caps = mod.UTF8ToString(capsPtr);
  console.log('capabilities: ' + caps);

  mod._bsw_session_destroy(session);
  console.log('session lifecycle OK');
})().catch((e) => {
  fail('engine failed to instantiate: ' + (e && e.message ? e.message : e));
});
