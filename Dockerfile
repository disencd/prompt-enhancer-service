FROM python:3.14-slim AS base

LABEL org.opencontainers.image.source="https://github.com/disencd/prompt-enhancer-service"
LABEL org.opencontainers.image.description="Voice-activated terminal-aware prompt enhancer"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/tmp/.uv-cache

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    xclip \
    && rm -rf /var/lib/apt/lists/*

# ── Build stage ──────────────────────────────────
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project
COPY src/ src/
COPY config.example.yaml ./
RUN uv sync --frozen --no-dev

# ── Runtime stage ────────────────────────────────
FROM base AS runtime

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/config.example.yaml /app/config.example.yaml

ENV PATH="/app/.venv/bin:$PATH"

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser
USER appuser

ENTRYPOINT ["prompt-enhancer"]
CMD ["--help"]
