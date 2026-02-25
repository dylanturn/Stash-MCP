FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY stash_mcp ./stash_mcp

# Install dependencies with uv
# Use --extra search to include semantic search support (numpy + pydantic-ai).
# Override SEARCH_EXTRA at build time to use a different embedder provider:
#   search            — sentence-transformers (local, default)
#   search-openai     — OpenAI embeddings
#   search-cohere     — Cohere embeddings
#   search-contextual — sentence-transformers + Anthropic contextual retrieval
# Example: docker build --build-arg SEARCH_EXTRA=search-openai .
ARG SEARCH_EXTRA=search
RUN uv sync --frozen --no-dev --extra ${SEARCH_EXTRA}

# Create persistent data directories
RUN mkdir -p /data/content /data/.stash-index /data/models

# Set environment variables
ENV STASH_CONTENT_ROOT=/data/content
ENV STASH_SEARCH_INDEX_DIR=/data/.stash-index
ENV STASH_HOST=0.0.0.0
ENV STASH_PORT=8000
ENV PYTHONUNBUFFERED=1
# Cache HuggingFace/sentence-transformers model weights under /data/models
# so they persist across container restarts when the volume is mounted.
ENV HF_HOME=/data/models

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run with uv
ENTRYPOINT ["uv", "run", "stash-mcp"]
