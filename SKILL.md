---
name: vision-augment
description: 视觉增强 MCP —— 为无视觉能力的 LLM（如 DeepSeek、GLM）提供看图、OCR 与文档解析。当用户需要分析图片/截图内容、识别图片中的文字、解析 docx/pdf/pptx/xlsx/html 文档时使用。工具：mcp_vision_augment_vision（task_type=reasoning|ocr|document）、mcp_vision_augment_clear_cache。
---

# vision-augment skill

为无视觉能力的 LLM 提供多模态能力（本地优先，视觉理解走视觉模型）。

## 何时使用

- 用户要求"看这张图/截图/描述图片内容" → `task_type=reasoning` + `task` 提问
- 用户要求"提取图片里的文字/OCR" → `task_type=ocr`（`language` 默认 ch）
- 用户要求"解析/总结这个文档（docx/pdf/pptx/xlsx/html）" → `task_type=document`

## 输入形式

`source` 支持：本地文件路径、`file://`、`data:` URL（内联小图）。`http(s)://` 默认关闭（防 SSRF），需服务端开启 `VISION_AUGMENT_ALLOW_URLS=true`。

## 配置（由服务端注入）

- 无 key 即可用：服务端自动探测本地 Ollama VL 模型兜底
- 推荐：`VISION_AUGMENT_CHANNELS` 配置 OpenAI 兼容端点（base_url + api_key + model，可多个按序降级）
- 本地 OCR/文档引擎通过 extras 安装：`uvx vision-augment[ocr,document]`
- 传输：默认 stdio；远程/Docker 场景服务端可开 `VISION_AUGMENT_TRANSPORT=streamable-http`（端点 `/mcp`）

## 调用示例

```json
mcp_vision_augment_vision(task_type="reasoning", source="C:\\Users\\me\\截图.png", task="描述这张截图的内容，并指出按钮布局")
mcp_vision_augment_vision(task_type="ocr", source="C:\\Users\\me\\票据.png", language="ch")
mcp_vision_augment_vision(task_type="document", source="C:\\Users\\me\\报告.docx")
```

## 返回值

统一 JSON envelope：`{task_type, tool_used, code, error, result, confidence, metadata}`。

- `code=0`：成功；`result` 为结果文本
- `code=1`：视觉通道全部失败；`code=2`：超时；`code=3`：输入无效
- `code=4`：本地引擎未安装（按 error 提示安装对应 extras）；`code=5`：内部错误

## 故障排查

- 报 `dependency_missing` → 服务端需装 extras：`uvx vision-augment[ocr]`（OCR）/ `[document]`（文档）
- 报 `channel_failed` → 检查通道配置或本地 Ollama 是否运行且有视觉模型
- 文档解析结果结构缺失（扫描 PDF/复杂表格）→ 改走 `task_type=ocr` 或将图片逐页提取
