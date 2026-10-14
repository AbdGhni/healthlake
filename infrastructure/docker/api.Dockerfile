# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements/app.lock /tmp/app.lock
RUN python -m venv /opt/healthlake-venv && /opt/healthlake-venv/bin/pip install --require-hashes -r /tmp/app.lock \
    && /opt/healthlake-venv/bin/pip check && rm /tmp/app.lock
COPY src /opt/healthlake/src
COPY config /opt/healthlake/config
RUN groupadd --system --gid 10001 healthlake && useradd --system --uid 10001 --gid 10001 --no-create-home healthlake
ENV PYTHONPATH=/opt/healthlake/src HEALTHLAKE_CONFIG_DIR=/opt/healthlake/config PATH=/opt/healthlake-venv/bin:${PATH}
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "healthlake.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
