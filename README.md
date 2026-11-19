# bambustudio-wasm

**BambuStudio 编译成 WebAssembly，在浏览器里原生运行。**

不是串流，不是 VNC，不是远程桌面 —— 是同一份 C++ 源码编译出的 WASM，
在浏览器本地用你的 CPU 和显卡跑。切片、建模、预览、参数面板，全部在客户端。

## 为什么这样可行

OrcaSlicer 已经有先例：[`Hiosdra/OrcaWasm`](https://github.com/Hiosdra/OrcaWasm)
把 OrcaSlicer v2.4.2 完整编译成 WASM（`slicer-mt.wasm` = 29 MB），
在浏览器里用 pthread 多线程本地切片，全程无服务器。

OrcaSlicer 是 BambuStudio 的 fork，共享同一套 libslic3r 血统。
本项目把这个方法搬到 BambuStudio v02.09.01.70 上。

## 构建在哪跑

**GitHub Actions。** 不是本地，不是那台 8 核无 GPU 的服务器。

| 项 | 值 |
|---|---|
| Runner | `ubuntu-latest`（GitHub 托管） |
| 耗时 | ~240 分钟（依赖 ~100min + 主构建 ~60min + 余量） |
| 工具链 | Emscripten 3.1.74 |
| 产物 | `bambu-slicer.wasm` + `.js` |

本地机器扛不住这个构建 —— 磁盘、内存、时间都不够。CI 是唯一实际可行的路径。

## 产物怎么分发

**Cloudflare Pages**，因为：

- Cloudflare 支持自定义响应头（`_headers` 文件），`SharedArrayBuffer` 需要 `Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: require-corp`；GitHub Pages 不支持。
- 单文件上限 25 MiB —— 所以 CI 里做 **brotli 预压缩**，前端用 `DecompressionStream` 解压，绕开限制（这也是 CDN 本来就在做的事，只是把压缩点前移）。

## 目录结构

```
patches/     BambuStudio 源码的 WASM 兼容补丁（可重复应用）
overrides/   替换掉不可用依赖（OCCT/OpenVDB/OpenCV）的桩实现
cmake/       自定义 Find 模块，让依赖在 WASM 下能被找到
bridge/      C ABI 桥接层，供 JS 调用
wasm/        Emscripten 链接目标与运行时胶水
scripts/     本地构建、冒烟测试
.github/     CI 工作流
```

## 许可证

BambuStudio 是 AGPL-3.0。本项目的补丁、桥接层和工作流同样以 AGPL-3.0 发布 ——
这是 AGPL-3.0 §13 的要求，也是使用它的前提。

原始项目：https://github.com/bambulab/BambuStudio
