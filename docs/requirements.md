# vision-augment 需求文档

> 状态：已评审（2026-08-11）
> 来源：`2026-08-11-vision-augment-project-brief.md`（立项文档）
> 配套：`docs/design.md`（设计文档）

---

## 1. 背景与定位

DeepSeek、GLM 5.2 等主力模型无原生视觉能力，无法看图、截图、文档、OCR。本项目开发一个**视觉识别 MCP server（+ skill）**，为无视觉 LLM 提供多模态能力。

三个核心诉求：

| 编号 | 诉求 | 含义 |
| --- | --- | --- |
| C1 | 简化配置、本地优先 | 不强制依赖云端，更简单、更便宜地接入 |
| C2 | OCR 和文档解析本地实现 | 视觉识别才使用视觉模型 |
| C3 | 不限制模型渠道 | 可自定义 OpenAI 兼容端点 |

## 2. 需求评估结论

**总体判断：差异化定位成立，需求可执行。**

- 调研（luma-mcp / ds-vision-skill / Qwen-MM-Plugins / LocalEyes / visor-mcp）显示"本地优先 + 视觉模型 + 自定义端点"三合一**无现成完整实现**，自研合理；
- 采用"组件复用 + 自有编排"策略（RapidOCR / markitdown / OpenAI 兼容协议均为成熟组件），把自研范围收敛到编排层（路由、降级链、超时、缓存、envelope），风险可控；
- 弃用"多云 key 强制竞速池"（ds-vision）、DashScope 绑定（Qwen-MM-Plugins）等重耦合设计，改为**顺序降级 + 可选通道**，正确简化。

**主要风险与对策：**

| 风险 | 对策 |
| --- | --- |
| 可选引擎体积大（paddlepaddle ~600MB、MinerU 更重），拖垮默认安装与 uvx 启动 | extras 拆分：`[ocr]` / `[ocr-full]` / `[document]` / `[full]`，默认零负担 |
| Windows 上 MinerU/DeepSpeed 基本不可用 | MinerU 标注为 Linux-only 可选升级链，文档写明平台支持矩阵 |
| 本地 OCR 质量上限低于云端（复杂版面） | 分级引擎 + confidence 字段 + 文档标注能力边界 |
| 无视觉通道时的体验断裂 | 默认探测本地 Ollama VL（无 key 即用），失败给 code-1 清晰错误 |

## 3. 用户与使用场景

- **主用户**：无视觉能力的 LLM 用户（DeepSeek / GLM），通过 Hermes 等 MCP harness 使用；
- **场景 A**：看图问答——截图分析、UI 走查、图片内容描述（`reasoning`）；
- **场景 B**：图片文字提取——票据、证件、截图文字（`ocr`）；
- **场景 C**：文档解析——docx / pdf / pptx / xlsx / html 转文本（`document`）。

## 4. 功能需求

优先级：P0 = 首版必须；P1 = 首版应有；P2 = 后续迭代。

| 编号 | 需求 | 优先级 | 验收标准 |
| --- | --- | --- | --- |
| FR-1 | 任务路由：`task_type` 分流（reasoning / ocr / document），每个任务映射唯一处理链 | P0 | 三种任务均可命中；未知 task_type 返回 code-3 envelope，不崩溃 |
| FR-2 | 视觉理解：OpenAI 兼容通道链，base_url + api_key + model 三元组，多通道按序降级 | P0 | 配置 2 个通道时，通道 1 失败自动落到通道 2；全部失败返回 code-1 envelope |
| FR-3 | 本地 Ollama 兜底：无配置 key 时探测本地 Ollama VL 模型 | P0 | Ollama 未运行/无 VL 模型时静默跳过，不影响配置通道 |
| FR-4 | 本地 OCR：RapidOCR（默认轻量） | P1 | 图片返回文本行 + 平均 confidence；引擎未安装时返回 code-4 envelope 并附安装指引 |
| FR-5 | 本地文档解析：markitdown（docx/pdf/pptx/xlsx/html → Markdown） | P1 | 文档返回文本；超大输出按 max_output_chars 截断并标注 truncated |
| FR-6 | 统一 JSON envelope：`{task_type, tool_used, code, error, result, confidence, metadata}` | P0 | 所有工具返回同一结构；错误码 0-5 语义固定 |
| FR-7 | 超时护栏：每通道独立超时，超时按通道失败处理并降级 | P0 | 通道超时不挂起整个请求，落 code-2 envelope |
| FR-8 | 缓存护栏：结果缓存 + TTL 上限，缓存目录可配置 | P1 | 同内容重复调用命中缓存（metadata.cache_hit=true）；TTL=0 关闭缓存；提供 clear_cache 工具 |
| FR-9 | 输入归一化：本地路径 / file:// / http(s)://（默认关闭）/ data:URL，统一为字节 + mime + sha256 | P0 | 四类输入均可用；不存在的路径返回 code-3 |
| FR-10 | 输出截断：`max_output_chars` 上限 | P1 | 超长结果截断且 metadata.truncated=true |
| FR-11 | 输入大小限制：`max_input_mb` 上限 | P1 | 超限输入返回 code-3 |
| FR-12 | 可选引擎升级链：PaddleOCR（中文增强）、MinerU（复杂文档，Linux-only） | P2 | 通过 extras 安装后启用，未安装时不影响默认链路 |
| FR-13 | 传输方式：stdio（默认）+ streamable-http（可选） | P1 | 默认 stdio 零配置；`VISION_AUGMENT_TRANSPORT=streamable-http` 启动后 `/mcp` 可完成 MCP 握手与 tools/list |
| FR-14 | 环境探测：`mcp_vision_augment_health` 返回通道/Ollama/引擎/缓存状态 | P1 | 返回 JSON 不含密钥；引擎缺失时附安装命令；支撑 skill 自动配置 |

## 5. 非功能需求

| 编号 | 需求 | 说明 |
| --- | --- | --- |
| NFR-1 | Python >= 3.12 | 开发环境 3.13 |
| NFR-2 | 跨平台 | Windows / macOS / Linux 均支持 stdio MCP；OCR/文档引擎的平台差异见设计文档 |
| NFR-3 | 安全：密钥不入库不打印 | api_key 仅注入 HTTP 头；日志不输出请求头/密钥 |
| NFR-4 | 安全：URL 抓取默认关闭 | 防 SSRF，`VISION_AUGMENT_ALLOW_URLS=true` 显式开启 |
| NFR-5 | 可观测：DEBUG 日志开关 | `VISION_AUGMENT_DEBUG=true` 输出模块日志 |
| NFR-6 | 可测试：核心逻辑零外部依赖可测 | 路由/envelope/输入/缓存单测不联网、不装重型引擎 |
| NFR-7 | 分发：uvx 一键运行 | `uvx vision-augment` 可直接跑 |

## 6. 边界与取舍（来自立项调研）

**取**：ds-vision 的降级链 + 错误码（0-5）+ JSON envelope + 端口探测；Qwen-MM-Plugins 的 skill+MCP 架构 + uvx 分发；luma-mcp 的 custom provider 抽象。

**弃**：ds-vision 多云 key 强制竞速池；Qwen-MM-Plugins 的 DashScope 绑定；Qwen-MM-Plugins core"直接喂模型"（依赖多模态主模型，对 DeepSeek 无效）。

**范围外（本期不做）**：视频帧提取、多图输入、图生图/图像编辑、远程 OCR 服务编排、MinerU 落地（P2 预留）。

## 7. 未覆盖问题评估（评审补充）

以下为评审时识别的、立项文档未显式覆盖的问题，逐项给出评估与处理结论。

| # | 问题 | 评估 | 结论 |
| --- | --- | --- | --- |
| 1 | **Windows 平台差异**：MinerU/DeepSpeed 依赖 CUDA Linux 生态，Windows 不可用；paddlepaddle Windows 可用但体积大 | 中影响。docs 若只字不提，Windows 用户会在 P2 链路上踩坑 | 设计文档写明平台支持矩阵；MinerU 标注 Linux-only 可选 |
| 2 | **依赖体积与 uvx 启动**：默认全装会把 paddlepaddle（~600MB）塞进每个 uvx 缓存 | 高影响，直接破坏 C1（简单便宜） | 已落地：extras 拆分，默认仅 mcp/httpx/pydantic |
| 3 | **大图与 token 预算**：视觉模型对超大图有输入上限，骨架未做压缩/缩放 | 中影响。超宽图可能被远端拒绝 | 本期依赖远端模型自身处理；max_input_mb 兜底；文档建议后续增加"长边缩放 + 切片"策略（P2） |
| 4 | **SSRF 风险**：source 支持 http(s) URL 后，MCP server 可能被诱导抓取内网 | 高影响（安全） | 已落地：URL 抓取默认关闭，显式开启 |
| 5 | **超大输入**：GB 级 PDF/图片直接读入内存 | 中影响 | 已落地：max_input_mb 默认 50MB |
| 6 | **并发与线程安全**：stdio 串行但 streamable-http 可并发；引擎实例跨线程复用 | 低-中影响 | httpx 每通道独立 Client；RapidOCR 引擎按语言单例缓存（onnxruntime 会话线程安全）；文档写明 |
| 7 | **错误码粒度**：0-5 六档能否覆盖"依赖缺失 vs 通道失败 vs 输入无效" | 低影响。6 档语义已能区分主要失败模式 | 保持 0-5 兼容立项文档，envelope 增加 metadata.error_type 细化说明 |
| 8 | **密钥安全**：api_key 可能经环境变量进子进程、日志可能泄露请求头 | 中影响（安全） | 已落地：Authorization 头不进日志；README 提示用 config 管理密钥 |
| 9 | **多语言 OCR**：RapidOCR 1.4 支持 ch/en/japan/korea/latin | 低影响 | 已落地：language 参数 + 语言白名单 |
| 10 | **markitdown 能力边界**：扫描版 PDF、复杂表格/公式会丢失结构 | 中影响（预期管理） | 文档标注：难版面走 `ocr` 或 P2 的 PaddleOCR-VL/MinerU 链 |
| 11 | **reasoning 缓存命中率**：缓存 key 含 task 文本，提问不同即不命中 | 低影响 | 语义正确（同图同问才命中），无副作用；文档写明 |
| 12 | **测试策略**：重型引擎无法进单测 | 低影响 | 已落地：适配器依赖注入，router 测试 mock provider；OCR/文档引擎留手动集成测试清单 |
| 13 | **发布与 CI**：立项未提版本管理与 CI | 中影响（长期维护） | 已落地：test.yml（矩阵 CI）+ release.yml（python-semantic-release 自动版本化 + Trusted Publisher/OIDC 发布 PyPI），见 design.md §14 |
| 14 | **多 harness 注册**：Hermes / Claude Desktop / OpenCode 配置格式不同 | 中影响（易用性） | README + SKILL.md 各给一份注册示例 |
| 15 | **缓存清理**：TTL 只能懒清理，用户无主动手段 | 低影响 | 已落地：`mcp_vision_augment_clear_cache` 工具 |
| 16 | **视觉结果长度**：远端模型可能返回超长文本 | 低影响 | reasoning 结果同样受 max_output_chars 约束（router 统一截断，metadata.truncated） |
| 17 | **未来方向**：视频帧、多图、PaddleOCR-VL、MinerU、流式输出 | — | 全部标 P2，不阻塞首版 |
| 18 | **HTTP 传输**：立项默认 stdio（本地单客户端），但 Docker 部署、远程服务器、多客户端并发场景 stdio 无法覆盖 | 中影响。SDK 原生支持 streamable-http（uvicorn 已随 `mcp[cli]` 安装），实现成本近零；主要风险是端口暴露 | 已落地：`VISION_AUGMENT_TRANSPORT=streamable-http`（默认 stdio 不变），默认绑定 127.0.0.1 + SDK 对 localhost 自动启用 DNS rebinding 防护；绑 `0.0.0.0` 属网络暴露，文档要求自备反代/鉴权（见 design.md §11） |

## 8. 里程碑

| 步骤 | 内容 | 状态 |
| --- | --- | --- |
| 1 | 项目骨架：pyproject + uv + MCP server + SKILL.md | ✅ 本期完成 |
| 2 | 视觉通道层：OpenAI 兼容 client + 本地 Ollama 探测 | ✅ 本期完成 |
| 3 | 本地 OCR（RapidOCR）/ 本地文档（markitdown） | ✅ 适配器完成，待真实引擎集成验证 |
| 4 | 任务路由 + JSON envelope + 超时/缓存护栏 | ✅ 本期完成 |
| 5 | 注册到 Hermes + 验证全链路 | ⏳ 待做（需先推送 GitHub） |
| 6 | 推送 GitHub（默认分支 master）+ 配置 PyPI Trusted Publisher + 首次发布 | ⏳ 待做（workflow 与 PSR 配置已完成） |
