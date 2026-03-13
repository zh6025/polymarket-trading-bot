# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Create a non-root user
RUN groupadd --gid 1001 botuser && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false botuser

WORKDIR /app

# Install system deps (needed for web3 / websocket-client)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory and set permissions
RUN mkdir -p /data && chown botuser:botuser /data /app

USER botuser

# Healthcheck: verify the process is running by checking if it's alive
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os, sys; sys.exit(0 if os.path.exists('/data/trading_bot.db') else 1)"

CMD ["python", "runner.py"]
