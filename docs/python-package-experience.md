# Python 包开发、测试、构建与发布经验报告

> 来源：vision-augment 项目（2026-08，Python MCP server + skill）
> 场景：从零搭建一个 uv 管理的 Python 包，完成 CI/发布/容器化全链路
> 适用范围：uv 项目、MCP server、PyPI 发布、GitHub Actions 自动化

---

## 1. 项目初始化与依赖管理（uv）

| 经验 | 要点 |
| --- | --- |
| 骨架 | src layout + hatchling + `uv sync`；`.python-version` 固定解释器 |
| 依赖锁定 | `uv lock` 生成 uv.lock 并**提交入库**；CI 用 `uv sync --locked` 严格校验一致性 |
| extras 分层 | 重型依赖（OCR 引擎、文档引擎）全部走 `[project.optional-dependencies]`，默认安装零负担 |
| 版本单一来源 | pyproject `project.version` 与代码 `__version__` 用发布工具同步（见 §5），不要双处手写 |

**extras 设计原则**：按"默认轻量 / 按需增强"分层——`ocr`（轻量引擎）、`ocr-full`（重型引擎）、`document`、`full`（全部）、`build`（CI 构建工具）。

## 2. 开发经验

- **配置 12-factor**：所有配置走 `APP_*` 前缀环境变量（无配置文件、无硬编码密钥），启动时 fail-fast 校验。
- **相对导入易错点**：子包内模块（`pkg/sub/mod.py`）用 `..`；包顶层模块（`pkg/mod.py`）用 `.`——顶层模块误写 `..` 会在运行时才报 "attempted relative import beyond top-level package"，**单测能立刻抓到**。
- **可测试性模式**：跨模块调用统一走"模块属性访问"（`from .x import y as z` 后 `z.fn()`），不要直接 `from .x.z import fn` 绑定函数——否则测试无法 monkeypatch（本项目为此改过一次）。

## 3. 测试经验（分层策略）

| 层 | 内容 | 依赖 |
| --- | --- | --- |
| 单元测试 | 路由/envelope/输入归一化/缓存，provider 用 monkeypatch 注入 | 零外部依赖 |
| 集成测试 | 子进程启动真实 server + MCP 握手（initialize → tools/list → 调工具） | mcp client |
| 发布冒烟 | 从构建产物（wheel）安装并验证工具可用 | uv build + uvx |

- **测试矩阵必须包含 Windows**：本项目 Windows 盘符路径被 `urlparse` 误判为 scheme（`C:\...` → scheme="c"）——ubuntu CI 抓不到，Windows runner 当场失败。
- 自定义 marker（如 `integration`）需在 `pyproject.toml` 注册，否则 pytest 告警。
- **发布前闸门**：release 流程里构建产物后、发布前跑冒烟测试（wheel 可安装 + 工具齐全），杜绝"测试绿但产物坏"。

## 4. 构建经验

- `uv build` 一次产出 sdist + wheel；发布前用 `zipfile` 检查 wheel 内容（模块齐全、入口点存在）。
- **Docker 镜像从构建上下文直接安装源码**（`COPY pyproject.toml uv.lock README.md ./` + `COPY src ./src` + `uv sync --frozen`），不依赖 PyPI 发布渠道，发布前后一致。
- **Dockerfile 必须 COPY README.md**：hatchling 构建 editable 时读取 pyproject 的 `readme` 字段，缺文件直接构建失败（CI 冒烟闸门拦截的第一个真实 bug）。
- **体积优化两板斧**：
  1. `uv sync ... && uv cache clean` —— wheel 缓存残留在镜像里是体积大头（本项目 ~200-400MB）；
  2. extras 用精选不要 `[all]`——`markitdown[all]` 会拉入 azure/音频/字幕等无关重依赖，`[pdf,docx,pptx,xlsx]` 即可；**extras 名必须实测**（不存在的名字 uv 只 warning 不报错，如 markitdown 的 `html`）。

## 5. 发布经验（python-semantic-release v10 + Trusted Publisher）

**版本化配置要点**（pyproject `[tool.semantic_release]`）：
- `version_toml` 同步 pyproject 版本；`version_variables` 同步代码内 `__version__`；
- `build_command` 内做 `uv lock` + `git add uv.lock` —— **版本提交顺带刷新锁文件**（否则发布后 `uv sync --locked` 全红）；
- `upload_to_repository = false`：PyPI 上传交给 `pypa/gh-action-pypi-publish`（OIDC Trusted Publisher），PSR 只负责版本化 + GitHub Release。

**版本行为（v10）**：
- 无 tag 时初始版本从**硬编码 0.0.0** 起步（不读 pyproject 已有版本）；
- `mask_initial_release` 默认 true：**首次发布 changelog 只有一行 "Initial Release"**，不解析 commits——不是 bug，是设计；第二次发布起自动正常（releases 段数 ≥2 后 mask 失效）；想首次也完整需 `mode="init"` + `mask_initial_release=false` + 删 CHANGELOG 重建。

**Trusted Publisher（免 token 发布）**：
- deploy job 需 `id-token: write`；PyPI 侧表单与 workflow **文件名**精确匹配（`release.yml`），environment 不填必须与 workflow 一致；
- 最小权限：release job 仅 `contents: write`，deploy job 仅 `id-token: write` + `contents: read`，workflow 级默认 `contents: read`。

**发布链路分层闸门**：源码级 CI（矩阵）→ 构建产物冒烟（release job 内）→ 容器冒烟（docker job 内）→ 推送。每层都拦截过真实问题。

## 6. 生态踩坑清单（可复用）

| 坑 | 现象 | 解法 |
| --- | --- | --- |
| Dependabot 更新 pyproject 不同步 uv.lock | CI `uv sync --locked` 失败 | 加"fix-lockfile"workflow：对 Dependabot PR 分支自动 `uv lock` + 提交（diff 为空则不提交防循环触发） |
| Dependabot 不自动创建 label | 报 "labels could not be found"、PR 无 label | label 需先在仓库创建；Mergify 依赖的 label 同理 |
| Mergify check-success 匹配矩阵 job | `check-success=test` 匹配不上 | 矩阵 check 名为 `test (ubuntu, 3.12)` 带参数 → 用正则 `~=^test( \(.*\))?$` |
| Docker Hub description | 上传 400 "Exceeded max number of bytes 100" | 上限 **100 字节**，中文 3 字节/字，文案需短 |
| setup-uv v8+ 无 major tag | `@v8` 失效 | v8 起只发布不可变 tag（`v8.3.2`/`v9.0.0`），必须钉具体版本 |
| FastMCP streamable-http 空 params initialize | 请求挂起不响应 | 探测就绪必须用合法握手载荷；客户端须同时接受 `application/json` + `text/event-stream`；请求体默认上限 4MB（需按输入上限调大） |
| GitHub Actions 版本漂移 | 各项目引用不同 major（checkout v4/v6/v7） | 用前以 releases 页实时核验；钉不可变版本 |

## 7. 最佳实践提炼

1. **测试是文档**：把"每层该验证什么"写进 workflow 注释，闸门位置一目了然。
2. **验证对象要精确**：冒烟/体积测试用"发布流程实际产出的那份产物"（复用已有 dist），而不是重新构建。
3. **生态经验要沉淀**：CLI/平台限制（字节数、scope、tag 政策）用一次记一次，跨项目复用。
4. **发布前全部可本地演练**：`uv build` → `uvx --from <wheel>` 冒烟 → （可选）TestPyPI 全流程，与 CI 产物验证互补。
