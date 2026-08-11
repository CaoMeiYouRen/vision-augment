---
name: vision-augment
description: 视觉增强 MCP —— 为无视觉能力的 LLM（如 DeepSeek、GLM）提供看图、OCR 与文档解析。当用户需要分析图片/截图内容、识别图片中的文字、解析 docx/pdf/pptx/xlsx/html 文档时使用。工具：mcp_vision_augment_vision（task_type=reasoning|ocr|document）、mcp_vision_augment_health（环境探测）、mcp_vision_augment_clear_cache。
---

# vision-augment skill

为无视觉能力的 LLM 提供多模态能力（本地优先，视觉理解走视觉模型）。本 skill 负责**使用引导**：触发时机、环境探测与自动配置、MCP 调用方法；能力本体由 MCP server 提供。

## 安装

```bash
# 从 GitHub 安装到全局（opencode / hermes-agent 等，按需调整 -a）
npx skills add CaoMeiYouRen/vision-augment -g -a opencode -a hermes-agent -y

# 或项目级（不指定 -g）：npx skills add CaoMeiYouRen/vision-augment
```

同时需注册 MCP server（`uvx vision-augment`，stdio 或 streamable-http），配置见仓库 README。

## 环境探测与自动配置（推荐先做）

**第一步总是调用 `mcp_vision_augment_health`**，拿到环境状态后按下表向用户反馈还缺什么、给什么命令。不要凭空猜测配置。

| health 字段 | 状态 | 向用户反馈（含命令） |
| --- | --- | --- |
| `channels` 为空 且 `ollama.reachable=false` | 视觉理解不可用 | 二选一：① 配置 `VISION_AUGMENT_CHANNELS`（OpenAI 兼容端点 JSON 数组，base_url/api_key/model）；② `ollama pull llava` 启动本地 Ollama VL 模型 |
| `channels` 非空 | 视觉理解已配置 | 无需操作（通道按序降级，失败自动兜底 Ollama） |
| `ollama.reachable=true` | 本地兜底可用 | 无需操作 |
| `ocr_engine.available=false` | OCR 引擎缺失 | 安装 extra：`uvx vision-augment[ocr]`（或重装：`uv tool install "vision-augment[ocr] @ git+..."`） |
| `document_engine.available=false` | 文档引擎缺失 | 安装 extra：`uvx vision-augment[document]` |
| `transport` / `cache` / `input_limits` | 信息项 | 一般无需反馈；`cache.ttl_seconds=0` 表示缓存关闭 |

若调用 `mcp_vision_augment_health` 失败（工具不存在/连不上），按顺序排查：MCP server 是否已注册（检查 harness 的 mcp_servers 配置，stdio 用 `command: uvx, args: [vision-augment]`）→ 服务端进程是否存活 → HTTP 模式端点 `/mcp` 是否可达。把排查结果与注册配置片段一并反馈用户。

## MCP 使用方法

### 工具

| 工具 | 说明 |
| --- | --- |
| `mcp_vision_augment_vision` | 主入口：`task_type`（reasoning 看图问答 / ocr 图片文字 / document 文档解析）+ `source`（路径 / file:// / http(s)://（需服务端开启）/ data:URL）+ `task`（reasoning 提问）+ `language`（OCR 语言，默认 ch） |
| `mcp_vision_augment_health` | 环境探测（见上节） |
| `mcp_vision_augment_clear_cache` | 清除本地结果缓存 |

### 任务选择

- 用户要求"看这张图/截图/描述图片内容/截图里的按钮" → `task_type=reasoning` + `task` 提问
- 用户要求"提取图片里的文字/OCR/识别票据" → `task_type=ocr`（`language` 默认 ch）
- 用户要求"解析/总结这个文档（docx/pdf/pptx/xlsx/html）" → `task_type=document`
- 多步编排：文档内容含图表 → 先 `document` 解析全文，再对图页/截图单独 `ocr` 或 `reasoning`

### 调用示例

```json
mcp_vision_augment_vision(task_type="reasoning", source="C:\\Users\\me\\截图.png", task="描述这张截图的内容，并指出按钮布局")
mcp_vision_augment_vision(task_type="ocr", source="C:\\Users\\me\\票据.png", language="ch")
mcp_vision_augment_vision(task_type="document", source="C:\\Users\\me\\报告.docx")
```

### 返回值（统一 JSON envelope）

`{task_type, tool_used, code, error, result, confidence, metadata}`：

- `code=0`：成功；`result` 为结果文本；`metadata.truncated=true` 表示被截断
- `code=1` 通道失败 / `code=2` 超时 → 检查通道配置或 Ollama；可重试
- `code=3` 输入无效 → 检查 source 路径/格式/大小
- `code=4` 本地引擎未安装 → 按 error 提示安装对应 extras（见环境探测表）
- `code=5` 内部错误 → 反馈用户查看服务端日志（`VISION_AUGMENT_DEBUG=true`）

### 反模式

- 扫描版 PDF / 复杂表格 → 不要用 `document`，改用 `ocr` 逐页提取（或提示用户这是文档引擎边界）
- 不要重复调用 `reasoning` 问同一张图同一问题（结果已缓存）
- 未先跑 `health` 就断言"配置齐全" → 环境可能已变化，探测是唯一可靠来源
