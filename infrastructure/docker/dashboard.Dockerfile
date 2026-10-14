# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements/dashboard.lock /tmp/dashboard.lock
RUN python -m venv /opt/dashboard-venv && /opt/dashboard-venv/bin/pip install --require-hashes -r /tmp/dashboard.lock \
    && /opt/dashboard-venv/bin/pip check && rm /tmp/dashboard.lock
COPY dashboards /opt/dashboard
RUN groupadd --system --gid 10001 healthlake && useradd --system --uid 10001 --gid 10001 --home-dir /tmp healthlake
ENV PATH=/opt/dashboard-venv/bin:${PATH} HOME=/tmp
WORKDIR /opt/dashboard
USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"]
CMD ["streamlit", "run", "app.py"]
