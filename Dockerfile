FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

# Health check: verify the bot process is alive
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD pgrep -f "python bot_runner.py" || exit 1

CMD ["python", "bot_runner.py"]
