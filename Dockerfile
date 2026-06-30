# Production-ready Dockerfile for AutoClaw Proxy

FROM python:3.11-slim

# Metadata
LABEL maintainer="AutoClaw Proxy"
LABEL description="Production proxy for AutoClaw API with tool calling support"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user
RUN groupadd -r appuser && \
    useradd -r -g appuser -u 1000 appuser && \
    mkdir -p /app /app/logs && \
    chown -R appuser:appuser /app

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY --chown=appuser:appuser proxy.py .
COPY --chown=appuser:appuser refresh_all.py .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8070

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8070/health', timeout=5).raise_for_status()" || exit 1

# Run proxy
CMD ["python", "-u", "proxy.py"]
