FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY README.md ./
COPY stash_mcp ./stash_mcp

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create content directory
RUN mkdir -p /data/content

# Set environment variables
ENV STASH_CONTENT_DIR=/data/content
ENV STASH_HOST=0.0.0.0
ENV STASH_PORT=8000
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Run the web server by default (includes REST API and UI)
# For MCP server, override with: python -m stash_mcp.server
CMD ["python", "-m", "stash_mcp.web_server"]
