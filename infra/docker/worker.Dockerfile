FROM python:3.12-slim-bookworm AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.txt ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app
WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=app:app . .
USER app
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 CMD ["python", "-m", "infra.local.health", "worker"]
CMD ["python", "-m", "infra.local.worker_entry"]
