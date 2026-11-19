import { createEngine } from './host.js';

const $ = (id) => document.getElementById(id);
const logEl = $('log');
const statusEl = $('status');
const barEl = document.querySelector('#bar > i');
const dropEl = $('drop');
const pickEl = $('pick');
const fileEl = $('file');

let engine = null;

function log(msg, cls) {
  const d = document.createElement('div');
  d.className = 'line' + (cls ? ' ' + cls : '');
  d.textContent = msg;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text) { statusEl.textContent = text; }
function setProgress(pct) { barEl.style.width = Math.max(0, Math.min(100, pct)) + '%'; }

async function boot() {
  try {
    log('加载引擎…', 'dim');
    setStatus('加载 WASM…');

    engine = await createEngine({
      onProgress: (pct, stage) => {
        setProgress(pct);
        setStatus(stage + ' ' + pct + '%');
      },
    });

    const caps = engine.capabilities();
    log('引擎就绪: ' + caps.engine + ' v' + caps.api, 'ok');
    log('能力: ' + caps.features.join(', '), 'dim');
    log('多线程: ' + (caps.threaded ? '是' : '否'), 'dim');

    setStatus('就绪');
    setProgress(0);
    pickEl.disabled = false;
  } catch (err) {
    log('启动失败: ' + err.message, 'err');
    setStatus('失败');
    // The most common cause is missing cross-origin isolation, which surfaces
    // as an opaque SharedArrayBuffer error. Say so instead of leaving the user
    // with a blank page.
    if (String(err.message).includes('SharedArrayBuffer') ||
        typeof SharedArrayBuffer === 'undefined') {
      log('', 'dim');
      log('页面缺少 COOP/COEP 响应头。SharedArrayBuffer 需要跨源隔离：', 'warn');
      log('  Cross-Origin-Opener-Policy: same-origin', 'warn');
      log('  Cross-Origin-Embedder-Policy: require-corp', 'warn');
      log('本地开发请用 npx serve 并配置上述头，或用 wrangler pages dev。', 'dim');
    }
  }
}

async function handleFile(file) {
  if (!engine) return;
  try {
    log('');
    log('载入 ' + file.name + ' (' + (file.size / 1024).toFixed(0) + ' KB)', 'dim');
    setStatus('载入模型…');

    const path = await engine.loadFile(file, '/tmp/' + file.name);
    log('模型已载入 ' + path, 'ok');

    setStatus('分析中…');
    const info = engine.info();
    log('信息: ' + JSON.stringify(info), 'dim');

    setStatus('就绪');
    log('可以切片了（下一版接入完整参数面板）', 'ok');
  } catch (err) {
    log('失败: ' + err.message, 'err');
    setStatus('失败');
  }
}

pickEl.addEventListener('click', () => fileEl.click());
fileEl.addEventListener('change', () => {
  if (fileEl.files[0]) handleFile(fileEl.files[0]);
});

['dragenter', 'dragover'].forEach((ev) =>
  dropEl.addEventListener(ev, (e) => {
    e.preventDefault();
    dropEl.classList.add('hot');
  })
);
['dragleave', 'drop'].forEach((ev) =>
  dropEl.addEventListener(ev, (e) => {
    e.preventDefault();
    dropEl.classList.remove('hot');
  })
);
dropEl.addEventListener('drop', (e) => {
  const f = e.dataTransfer && e.dataTransfer.files[0];
  if (f) handleFile(f);
});

boot();
