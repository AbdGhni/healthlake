#!/bin/sh
# HealthLake CLI entry point inside images (source tree on PYTHONPATH; no build backend needed at image build).
export PYTHONPATH=/opt/healthlake/src
exec /opt/healthlake-venv/bin/python -m healthlake.cli "$@"
