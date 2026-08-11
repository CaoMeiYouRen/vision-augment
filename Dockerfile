# vision-augment —— 本地构建的 MCP 视觉服务镜像（streamable-http）
#
# 从构建上下文直接安装项目源码（uv sync --frozen），不依赖 PyPI/GitHub。
# 构建：docker build -t vision-augment .
# 运行：docker compose up -d

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# uv（官方镜像，含 /uv 与 /uvx）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 先拷贝依赖清单以利用构建缓存（README.md 为 hatchling 构建所需）
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# 安装项目（lock 精确解析）+ 本地 OCR/文档引擎 extras，不装 dev 组；
# 清空 uv 下载缓存，避免 wheel 缓存残留在镜像中（体积大头）
RUN uv sync --frozen --no-group dev --extra ocr --extra document && uv cache clean

# 非 root 运行
RUN useradd -m appuser
USER appuser

ENV VISION_AUGMENT_TRANSPORT=streamable-http \
    VISION_AUGMENT_HOST=0.0.0.0 \
    VISION_AUGMENT_PORT=8000 \
    VISION_AUGMENT_CACHE_DIR=/home/appuser/.cache/vision-augment

EXPOSE 8000

# MCP 端点 GET 返回 405，健康检查用 TCP 探测
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), timeout=3)"

ENTRYPOINT ["/app/.venv/bin/vision-augment"]
