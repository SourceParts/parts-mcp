FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml README.md ./
COPY parts_mcp/__init__.py parts_mcp/__init__.py
RUN uv pip install --system ".[hosted]"

# Copy application source
COPY parts_mcp/ parts_mcp/

# Create non-root user
RUN groupadd --gid 1000 mcp && \
    useradd --uid 1000 --gid mcp --create-home mcp && \
    mkdir -p /tmp/parts-mcp-cache && \
    chown mcp:mcp /tmp/parts-mcp-cache

USER mcp

# Default env vars (overridden by env template at deploy time)
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_PATH=/mcp \
    PARTS_CACHE_DIR=/tmp/parts-mcp-cache \
    LOG_LEVEL=INFO

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

CMD ["python", "-m", "parts_mcp"]
