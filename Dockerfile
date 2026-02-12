FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY stash_mcp ./stash_mcp

# Install dependencies with uv
# Use --extra search to include semantic search support (numpy + pydantic-ai).
# Override SEARCH_EXTRA at build time to use a different provider:
#   docker build --build-arg SEARCH_EXTRA=search-openai .
ARG SEARCH_EXTRA=search
RUN uv sync --frozen --no-dev --extra ${SEARCH_EXTRA}

# Create content directory
RUN mkdir -p /data/content

# Set environment variables
ENV STASH_CONTENT_ROOT=/data/content
ENV STASH_HOST=0.0.0.0
ENV STASH_PORT=8000
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run with uv
ENTRYPOINT ["uv", "run", "stash-mcp"]
