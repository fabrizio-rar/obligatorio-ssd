"""Real Postgres for integration tests: a separate database (TEST_DATABASE_URL), created
if missing and migrated from scratch once per test session."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.ingest.load import LOAD_ORDER
from app.ingest.reader import Records, read_workbook

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATASET = BACKEND_DIR / "data/raw/MercaNova_dataset_obligatorio_2.xlsx"


def _create_database_if_missing(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    _create_database_if_missing(url)

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")  # also exercises the downgrade
    command.upgrade(config, "head")

    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Empty catalog for each test."""
    tables = ", ".join(name for name, _ in LOAD_ORDER)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="session")
def dataset_records() -> Records:
    """The real Excel, read once per session (reading it is the slow part)."""
    if not DATASET.exists():
        pytest.skip(f"dataset not found at {DATASET}")
    return read_workbook(DATASET)
