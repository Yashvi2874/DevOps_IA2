FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
WORKDIR /app

# Dependencies first, so this layer stays cached when only the code changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 10001 orderflow
COPY orderflow ./orderflow
USER orderflow

EXPOSE 8000
# Docker's own liveness check. Prometheus does the real monitoring.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# One worker with threads: the injected faults live in this one process.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "60", "orderflow.wsgi:app"]
