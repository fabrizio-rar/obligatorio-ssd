#!/bin/sh
# Startup: migrations -> first ingest (only if the catalog is empty) -> API.
set -e

alembic upgrade head
python -m scripts.ingest --if-empty
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
