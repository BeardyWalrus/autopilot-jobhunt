# Dockerfile for Glama MCP listing + general container use.
# Builds the autopilot-jobhunt MCP server (stdio transport).
FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/tarunlnmiit/autopilot-jobhunt" \
      org.opencontainers.image.description="Self-hosted AI job agent — MCP server" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install build deps first for layer caching.
COPY pyproject.toml requirements.txt README.md ./
COPY job_hunt ./job_hunt

# Install the package with the MCP extra.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[mcp]"

# Repo data files read from working dir at runtime.
COPY companies.json config.example.json ./

# API keys are supplied at runtime via env (-e) or an env file.
# The server starts and answers introspection without them; keys are
# only used when a tool is actually invoked.
ENV TINYFISH_API_KEY="" \
    OPENROUTER_API_KEY=""

# FastMCP serves over stdio.
CMD ["python", "-m", "job_hunt.mcp_server"]
