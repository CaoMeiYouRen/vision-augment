# vision-augment

本地优先的多模态视觉 MCP —— 为无视觉 LLM（DeepSeek、GLM 等）提供可自定义端点的看图 / OCR / 文档解析能力。

- **简化配置、本地优先**：不强制依赖云端；OCR 与文档解析全部本地完成
- **视觉理解用视觉模型**：OpenAI 兼容通道链，按序降级，最后兜底本地 Ollama VL（无 key 即用）
- **不限制模型渠道**：任意 OpenAI 兼容端点，`base_url + api_key + model` 三元组可配多个
- **uvx 一键分发**：`uvx vision-augment` 直接接入任意 MCP harness

## 架构

```
MCP client (Hermes / Claude / OpenCode ...)
   └─ mcp_vision_augment_vision(task_type=reasoning|ocr|document)
        └─ Router ─┬─ reasoning → OpenAI 兼容通道链 + Ollama 兜底
                   ├─ ocr       → RapidOCR（本地）→ PaddleOCR（可选升级）
                   └─ document  → markitdown（本地）→ PaddleOCR-VL / MinerU（可选升级）
```

所有工具返回统一 JSON envelope：`{task_type, tool_used, code, error, result, confidence, metadata}`，错误码 0-5。

## 快速开始

环境要求：Python >= 3.12，[uv](https://docs.astral.sh/uv/)。

### 方式一：无 key，本地 Ollama（默认）

```bash
ollama pull llava  # 或任一视觉模型（llava/vision/qwen2.5-vl/...）
uvx vision-augment
```

### 方式二：自定义 OpenAI 兼容端点（推荐）

```bash
uvx vision-augment[ocr,document]   # 按需安装本地 OCR/文档引擎
```

```yaml
# 注册到 Hermes config.yaml（其他客户端见下）
mcp_servers:
  vision-augment:
    command: uvx
    args: [vision-augment]
    env:
      VISION_AUGMENT_CHANNELS: '[{"base_url": "https://api.example.com/v1", "api_key": "${API_KEY}", "model": "qwen3.7-plus"}]'
```

无通道配置时自动探测本地 Ollama VL 模型作为兜底；通道配置优先。

### 本地 OCR/文档引擎（按需安装）

- 默认安装（`uvx vision-augment`）**只含视觉理解**（云端通道/Ollama）；OCR 与文档解析是本地引擎，按需通过 extras 安装：
  - `[ocr]`：RapidOCR（ONNX，跨平台轻量）——`uvx vision-augment[ocr]`
  - `[document]`：markitdown（docx/pdf/pptx/xlsx/html → Markdown）——`uvx vision-augment[document]`
- 引擎未安装时调用对应任务返回 `code=4 dependency_missing`（错误信息附安装命令）；随时可用 `mcp_vision_augment_health` 查看引擎可用状态
- ⚠️ **超时注意**：RapidOCR 引擎首次加载（ONNX 模型初始化）较慢，**首个 OCR 请求可能触发客户端 MCP 超时——重试一次即可**（引擎在 server 进程内缓存，第二次起秒回）；若频繁超时，调大客户端 MCP 工具超时（如 opencode 的 `toolTimeout`），或改用 HTTP 传输（见方式四）

### 方式三：从 GitHub 直接安装（未发布到 PyPI 前）

```bash
# 最新 master（PEP 508 语法：extras 在 @ 之前）
uvx "vision-augment[ocr,document] @ git+https://github.com/CaoMeiYouRen/vision-augment"

# 锁定 tag / commit
uvx "vision-augment @ git+https://github.com/CaoMeiYouRen/vision-augment@v0.1.0"

# 长期安装到 PATH（等价 pipx）
uv tool install "vision-augment[ocr] @ git+https://github.com/CaoMeiYouRen/vision-augment"
```

### 方式四：HTTP 传输（streamable-http）

适合 Docker 部署、远程服务器、多客户端并发场景（stdio 单进程只能服务一个客户端）：

```bash
VISION_AUGMENT_TRANSPORT=streamable-http VISION_AUGMENT_PORT=8000 uvx vision-augment
```

- 默认绑定 `127.0.0.1:8000`，MCP 端点 `/mcp`；SDK 对 localhost 自动启用 DNS rebinding 防护
- 跨机器访问：设置 `VISION_AUGMENT_HOST=0.0.0.0`，**并自行加反向代理/鉴权**（远程暴露是部署方责任）
- 客户端配置示例（Hermes）：

```yaml
mcp_servers:
  vision-augment:
    url: http://127.0.0.1:8000/mcp
    transport: streamable-http
```

> 注意：不要给 `streamable-http` 端点发送空 `params` 的 initialize 探测请求——SDK 会挂起该请求，用合法握手载荷探测。

### 方式五：Docker 部署（streamable-http）

直接使用 CI 构建发布的多架构镜像（`linux/amd64` + `linux/arm64`，发布到 Docker Hub / ghcr.io / 阿里云三个渠道，tag：`latest` / 日期 / `sha-<短hash>`）：

```bash
docker compose up -d
# 等价：docker run -d --name vision-augment -p 127.0.0.1:8000:8000 caomeiyouren/vision-augment
```

- 自定义镜像源：`DOCKER_IMAGE=ghcr.io/caomeiyouren/vision-augment docker compose up -d`
- 通道/密钥等配置通过环境变量或 `.env` 注入，示例见 [docker-compose.yml](docker-compose.yml)
- 本地开发构建：`docker build -t vision-augment .`（构建上下文直接安装源码，不依赖 PyPI）

与 Hermes 同 compose 网络接入（共享 `networks` 后走容器名）：

```yaml
mcp_servers:
  vision-augment:
    url: http://vision-augment:8000/mcp
    transport: streamable-http
```

### 注册到其他客户端

`env` 字段用于注入通道配置与密钥（与 Hermes 示例中的 env 同理）；通道为空时自动探测本地 Ollama 兜底。

```jsonc
// Claude Desktop: claude_desktop_config.json
{
  "mcpServers": {
    "vision-augment": {
      "command": "uvx",
      "args": ["vision-augment"],
      "env": {
        "VISION_AUGMENT_CHANNELS": "[{\"base_url\": \"https://api.example.com/v1\", \"api_key\": \"...\", \"model\": \"qwen3.7-plus\"}]"
      }
    }
  }
}
```

```jsonc
// OpenCode: opencode.json（--from 指定 extras 可启用本地 OCR/文档引擎）
{
  "mcp": {
    "vision-augment": {
      "type": "local",
      "command": ["uvx", "--from", "vision-augment[ocr,document]", "vision-augment"],
      "enabled": true,
      "env": {
        "VISION_AUGMENT_CHANNELS": "[{\"base_url\": \"https://api.example.com/v1\", \"api_key\": \"...\", \"model\": \"qwen3.7-plus\"}]"
      }
    }
  }
}
```

> 注意：修改配置（通道/模型/extras）后需**重启客户端会话**——MCP server 在启动时加载 env，不重启仍是旧配置。

## 工具

| 工具 | 说明 |
| --- | --- |
| `mcp_vision_augment_vision` | 入口：`task_type`（reasoning 看图问答 / ocr 图片文字 / document 文档解析）+ `source`（路径 / file:// / http(s):// / data:URL）+ `task` + `language` |
| `mcp_vision_augment_health` | 环境探测：通道/Ollama/OCR/文档引擎配置状态（不含密钥），供 agent 反馈缺失配置 |
| `mcp_vision_augment_clear_cache` | 清除本地结果缓存 |

## 安装与使用 Skill

仓库根目录的 `SKILL.md` 符合 [Agent Skills 规范](https://skills.sh/)，可通过 `npx skills` 生态一键安装（需仓库已公开）：

```bash
# 全局安装到 opencode / hermes-agent
npx skills add CaoMeiYouRen/vision-augment -g -a opencode -a hermes-agent -y

# 或项目级安装（不指定 -g）
npx skills add CaoMeiYouRen/vision-augment

# 查看已安装
npx skills list
```

Skill 安装后 agent 的工作方式：

1. **环境探测**：优先调用 `mcp_vision_augment_health` 检查通道/Ollama/引擎状态，自动向你反馈还缺哪些配置及安装命令（如 `uvx vision-augment[ocr]`）
2. **任务路由**：看图 → `reasoning`；图片文字 → `ocr`；文档解析 → `document`，由 skill 指引 agent 选择
3. **故障闭环**：错误码 0-5 对应的处置路径写在 SKILL.md 中

手动安装：把 `SKILL.md` 复制到 `~/.config/opencode/skills/vision-augment/`（opencode）或 `~/.hermes/skills/`（Hermes）等目录即可。

## 配置（环境变量，均有默认值）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VISION_AUGMENT_CHANNELS` | `[]` | OpenAI 兼容通道 JSON 数组 |
| `VISION_AUGMENT_OLLAMA_URL` | `http://127.0.0.1:11434` | 本地 Ollama 地址 |
| `VISION_AUGMENT_CACHE_TTL_SECONDS` | `86400` | 缓存 TTL（0=关闭） |
| `VISION_AUGMENT_CACHE_DIR` | `~/.cache/vision-augment` | 缓存目录 |
| `VISION_AUGMENT_MAX_INPUT_MB` | `50` | 输入大小上限 |
| `VISION_AUGMENT_MAX_OUTPUT_CHARS` | `20000` | 输出截断上限 |
| `VISION_AUGMENT_ALLOW_URLS` | `false` | 允许 http(s) 输入（防 SSRF，默认关闭） |
| `VISION_AUGMENT_DEBUG` | `false` | DEBUG 日志 |
| `VISION_AUGMENT_TRANSPORT` | `stdio` | 传输方式：`stdio` / `streamable-http` |
| `VISION_AUGMENT_HOST` | `127.0.0.1` | HTTP 绑定地址 |
| `VISION_AUGMENT_PORT` | `8000` | HTTP 端口 |

完整说明见 [docs/design.md](docs/design.md#10-配置-schema环境变量)。

## 开发

```bash
uv sync            # 安装开发环境（基础依赖）
uv run pytest      # 单元测试（不依赖重型引擎）
uv run ruff check  # 代码检查
```

安装可选引擎做集成验证：

```bash
uv sync --extra ocr --extra document   # RapidOCR + markitdown
# 或全量：uv sync --all-extras（含 PaddleOCR，体积大）
```

## 发布（CI 自动）

push 到 `master` 后，[release workflow](.github/workflows/release.yml) 由 [python-semantic-release](https://python-semantic-release.readthedocs.io/) 根据 conventional commits 自动版本化（pyproject + `__version__` + CHANGELOG + tag + GitHub Release），并通过 **Trusted Publisher（OIDC，免 token）** 发布到 PyPI。

Trusted Publisher 配置（PyPI → Publishing → Trusted Publishers → Add pending publisher）：

| 字段 | 值 |
| --- | --- |
| PyPI Project Name | `vision-augment` |
| Owner | `CaoMeiYouRen` |
| Repository name | `vision-augment` |
| Workflow name | `release.yml` |
| Environment name | 留空 |

首次发布后 `uvx vision-augment` 即生效。手动发布备选：`uv build && uv publish`（需 `UV_PUBLISH_TOKEN`）。

## 文档

- [需求文档](docs/requirements.md)（含需求评估与未覆盖问题评估）
- [设计文档](docs/design.md)（架构、envelope 契约、通道链、缓存、平台支持矩阵）
- [SKILL.md](SKILL.md)（agent 使用技能）

## 许可证

[MIT](LICENSE) © 2026 CaoMeiYouRen
