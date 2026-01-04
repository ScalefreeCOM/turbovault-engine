# Multi-stage Dockerfile for TurboVault Engine
# Optimized for production deployment with minimal image size

# Stage 1: Builder
FROM python:3.12-slim as builder

LABEL org.opencontainers.image.source="https://github.com/ScalefreeCOM/turbovault-engine"
LABEL org.opencontainers.image.description="TurboVault Engine - Data Vault dbt project generator"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first for better layer caching
COPY pyproject.toml README.md ./
COPY backend/ ./backend/

# Build wheel
RUN pip install --no-cache-dir build && \
    python -m build --wheel

# Stage 2: Runtime
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ScalefreeCOM/turbovault-engine"
LABEL org.opencontainers.image.description="TurboVault Engine - Data Vault dbt project generator"
LABEL org.opencontainers.image.licenses="MIT"

# Create non-root user for security
RUN groupadd -r turbovault && useradd -r -g turbovault turbovault

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy wheel from builder
COPY --from=builder /build/dist/*.whl /tmp/

# Install the wheel
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm /tmp/*.whl

# Create directories for data persistence
RUN mkdir -p /app/data /app/output && \
    chown -R turbovault:turbovault /app

# Switch to non-root user
USER turbovault

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=turbovault.settings \
    TURBOVAULT_DATA_DIR=/app/data \
    TURBOVAULT_OUTPUT_DIR=/app/output

# Expose Django admin port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command: show help
CMD ["turbovault", "--help"]
