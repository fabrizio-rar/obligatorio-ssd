#!/bin/sh
# Startup: migrations -> first ingest (only if the catalog is empty) -> embeddings -> API.
set -e

alembic upgrade head
python -m scripts.ingest --if-empty
# Only embeds new/changed products (0 API calls when nothing changed). A failure here
# (no credit, OpenAI down) must not stop the app: search falls back to full-text.
python -m scripts.index_embeddings || echo "WARNING: embeddings step failed; the API starts anyway"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
