# Use the official uv image as the base so `uv` is already present and
# matches the target platform automatically when building with buildx.
# Previously this Dockerfile did `FROM python:3.12-slim` and then
# `COPY --from=ghcr.io/astral-sh/uv:latest /uv ...`, which resolved the
# uv binary against the *builder's* platform rather than the target,
# producing `exec format error` on mismatched architectures (e.g. an
# arm64 build run on amd64 nodes).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Set working directory
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY stash_mcp ./stash_mcp

# Install dependencies with uv
# Use --extra search to include semantic search support (numpy + fastembed,
# i.e. ONNX Runtime — no torch/CUDA: ~0.7 GB unpacked / ~0.17 GB compressed
# instead of ~12 GB / ~4.4 GB with the torch + CUDA wheels).
# Override SEARCH_EXTRA at build time to use a different embedder provider:
#   search            — local ONNX Runtime via fastembed + BM25 hybrid
#                       retrieval (default; model strings onnx:<model>)
#   search-torch      — local PyTorch via sentence-transformers (model strings
#                       sentence-transformers:<model>; pulls torch + CUDA libs)
#   search-openai     — OpenAI embeddings
#   search-cohere     — Cohere embeddings
#   search-contextual — ONNX Runtime + Anthropic contextual retrieval
#   search-hybrid     — alias of `search` (kept for compatibility)
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
# Cache embedding model weights under /data/models so they persist across
# container restarts when the volume is mounted. The ONNX backend writes to
# $STASH_MODEL_CACHE_DIR/fastembed (default /data/models/fastembed); HF_HOME
# covers the torch/sentence-transformers path (search-torch extra).
ENV STASH_MODEL_CACHE_DIR=/data/models
ENV HF_HOME=/data/models

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run with uv
ENTRYPOINT ["uv", "run", "stash-mcp"]
