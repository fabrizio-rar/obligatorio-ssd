"""Ingest pipeline: Excel -> normalize -> validate -> load (docs/PLAN.md §8).

Step 5 (index embeddings) is added with N8 and step 6 (demo user) with N3.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from app.ingest.load import load_catalog
from app.ingest.reader import Records, read_workbook
from app.ingest.report import IngestReport
from app.ingest.validate import validate_catalog


def ingest_records(
    session: Session, records: Records, dataset: str, reset_inventory: bool = False
) -> IngestReport:
    """Validate and load already-read records in ONE transaction (all or nothing)."""
    report = IngestReport(dataset=dataset, reset_inventory=reset_inventory)
    data = validate_catalog(records, report)
    try:
        report.tables = load_catalog(session, data, reset_inventory)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return report


def ingest_file(session: Session, path: Path, reset_inventory: bool = False) -> IngestReport:
    return ingest_records(session, read_workbook(path), str(path), reset_inventory)
