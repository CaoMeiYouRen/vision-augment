# vision-augment 设计文档

> 状态：v1（2026-08-11）
> 配套：`docs/requirements.md`（需求文档）

---

## 1. 架构总览

```
                    ┌─────────────────────────────────────────┐
   MCP client  ───▶ │  mcp_vision_augment_vision (单一入口)    │
   (Hermes/Claude/  │  mcp_vision_augment_clear_cache          │
    OpenCode/...)   └───────────────────┬─────────────────────┘
                                        │ task_type
                                        ▼
                              ┌───────────────────┐
                              │ Router（任务路由）  │ 修复 ds-vision P1-①
                              └─────────┬─────────┘
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
             reasoning              ocr                 document
                    │                   │                   │
        ┌───────────┴───────────┐      │                   │
        ▼                       ▼      ▼                   ▼
┌─────────────────┐     ┌──────────────┐   ┌──────────────────┐
│ Vision 通道链     │     │ RapidOCR     │   │ markitdown        │
│ 通道1 → 通道2 →   │     │ (extras:ocr) │   │ (extras:document) │
│ Ollama 探测兜底   │     │ PaddleOCR ⬆  │   │ PaddleOCR-VL ⬆    │
└─────────────────┘     └──────────────┘   │ MinerU ⬆ (Linux)  │
                                            └──────────────────┘
        ┌──────────────────────────────────────────────────┐
        │ 横切：Input 归一化 / TTLCache / Envelope / Config │
        └──────────────────────────────────────────────────┘
```

设计要点：

- **单一入口工具 + 内部路由**：模型只需学会一个工具，路由决策由 server 完成（修复 ds-vision 的路由断裂）；
- **顺序降级而非竞速池**：通道按配置顺序尝试，失败落到下一个，最后 Ollama 兜底——简单、可控、无并发竞态；
- **本地引擎懒加载**：OCR/文档引擎通过 extras 安装，未安装时返回 code-4 指引而非崩溃。

## 2. 模块职责

| 模块 | 职责 | 关键依赖 |
| --- | --- | --- |
| `server.py` | FastMCP 装配、工具定义、日志初始化 | mcp |
| `router.py` | task_type 分流、降级编排、envelope 组装、输出截断、缓存存取 | 内置 |
| `health.py` | 环境探测：通道/Ollama/引擎可用性/缓存/输入限制（不含密钥），支撑 skill 自动配置 | 内置 |
| `config.py` | `VISION_AUGMENT_*` 环境变量解析 → `Settings`/`VisionChannel` | 内置 |
| `envelope.py` | 统一输出结构 + 错误码 0-5 + 异常类型体系 | 内置 |
| `input.py` | source 归一化（路径/file:///URL/data:）、sha256、临时文件物化 | httpx |
| `cache.py` | 磁盘 TTL 缓存，原子写入，可禁用 | 内置 |
| `vision/client.py` | OpenAI 兼容通道链、降级、每通道超时 | httpx |
| `vision/ollama.py` | 本地 Ollama VL 模型探测 | httpx |
| `ocr/rapidocr.py` | RapidOCR 适配（懒加载、语言白名单、confidence 均值） | rapidocr-onnxruntime * |
| `document/markitdown.py` | markitdown 适配（懒加载） | markitdown[all] * |

\* 仅通过 extras 安装（`ocr` / `document` / `full`）。

## 3. 数据流（以 reasoning 为例）

1. 客户端调用 `mcp_vision_augment_vision(task_type="reasoning", source, task)`；
2. Router 校验 task_type → 不合规返回 code-3 envelope；
3. `resolve_source` 归一化输入（读取/抓取/解码 + sha256），失败返回 code-3；
4. 计算缓存 key `reasoning:{sha256}:{task}`，命中直接返回 envelope（metadata.cache_hit=true）；
5. `describe_image` 依次尝试配置通道 → Ollama 探测兜底；单通道超时/失败降级；
6. 结果按 `max_output_chars` 截断，组装 envelope，写缓存，返回。

## 4. JSON envelope 契约

```json
{
  "task_type": "reasoning",
  "tool_used": "vision:qwen3.7-plus@https://api.example.com",
  "code": 0,
  "error": null,
  "result": "图片内容是一只猫……",
  "confidence": 1.0,
  "metadata": { "channel": "qwen3.7-plus@https://api.example.com", "model": "qwen3.7-plus", "latency_ms": 1234, "cache_hit": false, "truncated": false }
}
```

错误码（与立项文档一致）：

| code | error_type | 触发 |
| --- | --- | --- |
| 0 | success | 正常 |
| 1 | channel_failed | 所有视觉通道失败 / 无可用通道 |
| 2 | timeout | 通道超时 |
| 3 | invalid_input | 输入无效 / 不可访问 / 超限 |
| 4 | dependency_missing | 本地引擎未安装 |
| 5 | internal_error | 未预期异常 |

## 5. 视觉通道链

**通道配置**（借鉴 luma-mcp custom provider）：

```json
VISION_AUGMENT_CHANNELS=[
  {"base_url": "https://api.example.com/v1", "api_key": "sk-...", "model": "qwen3.7-plus", "timeout_seconds": 60, "extra_headers": {"X-Tenant": "a"}},
  {"base_url": "https://api2.example.com/v1", "api_key": "sk-...", "model": "gpt-4.1-mini"}
]
```

- 请求体为 OpenAI `chat/completions` 格式，图片以 `data:` URL 注入 `image_url`；
- 每通道独立超时（`timeout_seconds`，缺省 60s），超时 = 通道失败，降级到下一通道；
- **兜底**：通道全部失败后探测本地 Ollama（`/api/tags`，5s 超时），发现 VL 模型（llava/vision/-vl/minicpm/moondream/gemma3 等标记）即追加为最后通道；探测结果 30s TTL 缓存，避免 Ollama 停服时每次请求白等超时；
- 全部失败 → 抛最后一次错误，envelope code 1/2；
- 显式配置优先于本地兜底（用户配了远程端点就是明确意图）。

## 6. OCR 管线（本地）

```
task_type=ocr → RapidOCR(ONNX) → 文本行 + 平均 confidence
                          ⬆ 升级：PaddleOCR（extras: ocr-full，中文更强，~600MB）
```

- **RapidOCR 1.x API 约束**：适配器按 `RapidOCR(lang=...).ocr(path)` 编写（返回 `[box, text, score]` 行），pyproject 固定 `rapidocr-onnxruntime>=1.4,<2`；
- 语言白名单：`ch / en / japan / korea / latin`，非法值回退 `ch`；
- 引擎按语言单例缓存（首次加载 ONNX 模型较慢，之后复用；onnxruntime 会话线程安全，可并发推理）；
- 输出为纯文本行（保留原始顺序，不做版面重建）。

## 7. 文档解析管线（本地）

```
task_type=document → markitdown → Markdown 文本（确定性，confidence=1.0）
                 ⬆ 升级：PaddleOCR-VL 流水线（P2）
                 ⬆ 升级：MinerU（P2，Linux-only）
```

- markitdown 覆盖 docx / pdf / pptx / xlsx / html / md 等；
- **能力边界**：扫描版 PDF、复杂表格/公式会丢失结构——文档明确告知用户改走 `ocr` 或升级链；
- 输出按 `max_output_chars`（默认 20000 字符）截断，`metadata.truncated=true` 标记。

## 8. 输入归一化

| 形式 | 处理 | 备注 |
| --- | --- | --- |
| 本地路径 | 直接读文件 | 相对路径以 server 工作目录为准 |
| `file://` | 解析路径后读取 | — |
| `http(s)://` | httpx 抓取 | **默认拒绝**（防 SSRF），`VISION_AUGMENT_ALLOW_URLS=true` 开启 |
| `data:...;base64,...` | base64 解码 | 便于模型直接内联小图 |

- 全部输入校验 `max_input_mb`（默认 50MB）与空内容：`data:` URL 先按 base64 长度预检再解码，http(s) 流式下载、超限即中止（护栏不可绕过）；
- `sha256` 作为内容身份，参与缓存 key；
- bytes 型输入（data:/URL）在 `resolve_source` 阶段就物化出本地临时文件（`<cache_dir>/tmp`），供只接受路径的引擎使用。

## 9. 缓存设计

- **key**：`{task_type}:{content_sha256}:{参数}`（reasoning 含 task 文本、ocr 含语言、document 仅内容哈希）；
- **TTL**：默认 24h，`VISION_AUGMENT_CACHE_TTL_SECONDS=0` 关闭；过期条目懒清理（读时发现即删）；
- **写入**：scratch 文件 + `os.replace` 原子替换，并发安全；
- **存储**：`<cache_dir>/*.json`，默认 `~/.cache/vision-augment`；
- **清理**：`mcp_vision_augment_clear_cache` 工具主动清空；
- 命中时 envelope 保留原结构，`metadata.cache_hit=true`、`latency_ms=0`。

## 10. 配置 schema（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VISION_AUGMENT_CHANNELS` | `[]` | OpenAI 兼容通道 JSON 数组 |
| `VISION_AUGMENT_OLLAMA_URL` | `http://127.0.0.1:11434` | 本地 Ollama 地址 |
| `VISION_AUGMENT_OLLAMA_TIMEOUT_SECONDS` | `5` | Ollama 探测超时 |
| `VISION_AUGMENT_CACHE_DIR` | `~/.cache/vision-augment` | 缓存目录 |
| `VISION_AUGMENT_CACHE_TTL_SECONDS` | `86400` | 缓存 TTL，0=关闭 |
| `VISION_AUGMENT_TIMEOUT_SECONDS` | `60` | URL 抓取等通用超时 |
| `VISION_AUGMENT_MAX_INPUT_MB` | `50` | 输入大小上限 |
| `VISION_AUGMENT_MAX_OUTPUT_CHARS` | `20000` | 输出截断上限 |
| `VISION_AUGMENT_ALLOW_URLS` | `false` | 允许 http(s) 输入（SSRF 开关） |
| `VISION_AUGMENT_DEBUG` | `false` | DEBUG 日志 |
| `VISION_AUGMENT_TRANSPORT` | `stdio` | 传输方式：`stdio` / `streamable-http` |
| `VISION_AUGMENT_HOST` | `127.0.0.1` | HTTP 绑定地址 |
| `VISION_AUGMENT_PORT` | `8000` | HTTP 端口 |

密钥只经环境变量/配置管理注入，不进代码、不进日志。

## 11. 传输方式（stdio / streamable-http）

| 维度 | stdio（默认） | streamable-http |
| --- | --- | --- |
| 适用场景 | 本地单客户端（Hermes/Claude/OpenCode 桌面） | Docker、远程服务器、多客户端并发 |
| 进程模型 | 一客户端一进程 | 单进程多客户端（共享缓存/引擎实例，线程安全） |
| 配置 | 零配置 | `VISION_AUGMENT_TRANSPORT=streamable-http` + host/port |
| 端点 | — | `http://host:port/mcp`（MCP streamable-http，SSE 响应） |
| 安全默认 | 本地进程 | 默认绑定 `127.0.0.1`；SDK 对 localhost 自动启用 DNS rebinding 防护 + allowed_hosts/origins |
| 风险 | 无网络暴露 | 绑 `0.0.0.0` 即网络暴露，需自备反代/鉴权 |

实现说明：

- `FastMCP("vision-augment", host=..., port=...)` + `server.run(transport="streamable-http")`，uvicorn 由 `mcp[cli]` 提供；
- 请求体上限按 `2 × max_input_mb` 设置（SDK 默认仅 4MB，容纳 base64 膨胀后的 data: URL）；
- 有状态会话：initialize 响应头 `Mcp-Session-Id`，后续请求需带该头 + `MCP-Protocol-Version`；
- 客户端必须同时接受 `application/json` 与 `text/event-stream`（SDK 强制，返回 SSE 帧）；
- **已知 SDK 行为**：向 `/mcp` 发送空 `params` 的 initialize 会使服务端挂起请求不响应——探测就绪应使用合法握手载荷；

## 12. 平台支持矩阵

| 组件 | Windows | macOS | Linux | Docker |
| --- | --- | --- | --- | --- |
| MCP server（stdio） | ✅ | ✅ | ✅ | ✅ |
| MCP server（streamable-http） | ✅ | ✅ | ✅ | ✅（正式形态） |
| RapidOCR（onnxruntime） | ✅ | ✅ | ✅ | ✅（镜像内置 ocr extra） |
| markitdown | ✅ | ✅ | ✅ | ✅（镜像内置 document extra） |
| PaddleOCR（paddlepaddle） | ✅（体积大） | 🟡 | ✅ | ⚠️（未内置，按需扩展） |
| MinerU（P2，DeepSpeed/CUDA） | ❌ | ❌ | ✅ | ⚠️ |

**Docker 部署**（`docker-compose.yml` + `Dockerfile`）：

- 镜像由 CI（`.github/workflows/docker.yml`）构建发布：`linux/amd64` + `linux/arm64` 双架构，推送 docker.io / ghcr.io / registry.cn-hangzhou.aliyuncs.com 三渠道（tag：`latest` / 日期 / `sha-<短hash>`）；
- compose 通过 `image: ${DOCKER_IMAGE:-caomeiyouren/vision-augment}` 直接拉取启动（不依赖本地构建）；
- Dockerfile 从构建上下文安装源码（`uv sync --frozen --no-group dev --extra ocr --extra document`），**不依赖 PyPI**；非 root 运行；HEALTHCHECK 用 TCP 探测（MCP 端点 GET 返回 405）；
- 发布前闸门：CI 先构建当前平台镜像并跑容器冒烟（MCP initialize 握手），通过后才多架构推送；
- 暴露面：compose 默认映射 `127.0.0.1:8000`；接入 Hermes 同 compose 网络时可注释端口映射，直接用容器名访问。

## 13. 测试策略

- **单测（无外部依赖）**：envelope 形状与错误码、输入归一化（含边界）、缓存 TTL、路由（provider 以 monkeypatch 注入，覆盖 success / 降级失败 / 依赖缺失 / 内部错误 / 截断 / 缓存命中）；
- **手动集成清单**（需 extras）：真实 RapidOCR 跑一张含文字图片、markitdown 跑一个 docx/pdf、真实 OpenAI 兼容端点跑 reasoning、本地 Ollama VL 探测；
- 重型引擎（PaddleOCR/MinerU）不进 CI，只做手动验证。

## 14. 发布与分发

- 入口：`[project.scripts] vision-augment = "vision_augment:main"`；
- 运行：`uvx vision-augment`（PyPI 发布后）/ `uvx "vision-augment @ git+https://github.com/CaoMeiYouRen/vision-augment"`（发布前，extras 写在 `@` 前）；
- **版本与发布（CI 自动）**：`python-semantic-release` v10 配置见 pyproject `[tool.semantic_release]`：
  - `branch = "master"`，conventional commits 驱动 bump；
  - `version_toml` 同步 `pyproject.toml:project.version`，`version_variables` 同步 `__init__.py:__version__`；
  - `build_command`：容器内 `pip install -e '.[build]'`（装 uv）→ `uv lock` + `git add uv.lock`（release 提交内一并更新锁文件）→ `uv build`；
  - `[tool.semantic_release.publish] upload_to_repository = false`：PyPI 上传交给 pypa action（OIDC），PSR 只传 GitHub Release assets；
- **CI**：
  - `test.yml`：push/PR 触发，ubuntu + windows × py3.12/3.13 矩阵，`uv sync --locked` + ruff + pytest；
  - `release.yml`：push master 触发，release job（PSR 版本化 + 构建 + GitHub Release）→ deploy job（`id-token: write` + `pypa/gh-action-pypi-publish`，Trusted Publisher 免 token）；
  - Trusted Publisher 表单：project `vision-augment` / owner `CaoMeiYouRen` / repo `vision-augment` / workflow `release.yml` / environment 留空；
- 手动发布备选：`uv build && uv publish`（`UV_PUBLISH_TOKEN`）。

## 15. 目录结构

```
vision-augment/
├── pyproject.toml / uv.lock / .python-version / LICENSE / README.md / SKILL.md
├── docs/
│   ├── requirements.md
│   └── design.md
├── src/vision_augment/
│   ├── server.py / router.py / health.py / config.py / envelope.py / input.py / cache.py
│   ├── vision/  (client.py, ollama.py)
│   ├── ocr/     (rapidocr.py)
│   └── document/(markitdown.py)
└── tests/
```

## 16. 决策记录（ADR 简表）

| 决策 | 选项 | 结论 | 理由 |
| --- | --- | --- | --- |
| 工具形态 | 单一入口（task_type 分流） vs 多工具 | 单一入口 | 模型只需学一个工具；路由在 server 侧，避免模型选错 |
| 通道策略 | 竞速池 vs 顺序降级 | 顺序降级 | 简单可控、无并发竞态；符合"简单便宜"诉求 |
| Ollama 位置 | 最前（本地优先） vs 最后兜底 | 最后兜底 | 显式配置优先于隐式默认；无 key 用户仍可即用 |
| 默认依赖 | 全量 vs extras | extras | 保 uvx 轻量启动，重引擎按需安装 |
| URL 输入 | 默认允许 vs 默认关闭 | 默认关闭 | SSRF 防护，本地优先定位一致 |
| 传输方式 | stdio-only vs 双传输 | 双传输，stdio 默认 | SDK 原生支持，成本近零；覆盖 Docker/远程/多客户端场景（见 §11） |
| OCR 引擎版本 | rapidocr 2.x vs 1.x 固定 | 固定 `>=1.4,<2` | 2.x API 变动大，1.x API 稳定且满足需求 |
