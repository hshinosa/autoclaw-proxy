FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask requests

# Copy files
COPY proxy.py .
COPY autoclaw_accounts.json .

# Expose port
EXPOSE 8070

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8070/health').raise_for_status()"

# Run proxy
CMD ["python", "proxy.py"]
