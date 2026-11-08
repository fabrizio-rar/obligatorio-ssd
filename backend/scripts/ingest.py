"""Load the Excel dataset into the DB.

python -m scripts.ingest              # upsert catalog, keep current inventory
python -m scripts.ingest --reset      # also overwrite inventory with the Excel values
python -m scripts.ingest --if-empty   # do nothing if the catalog is already loaded
"""

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.db import get_session_factory
from app.ingest.load import catalog_is_empty
from app.ingest.pipeline import ingest_file
from app.ingest.reader import DatasetError


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=settings.dataset_path)
    parser.add_argument("--report", type=Path, default=settings.ingest_report_path)
    parser.add_argument(
        "--reset", action="store_true", help="overwrite inventory with the Excel values"
    )
    parser.add_argument(
        "--if-empty", action="store_true", help="skip if the catalog already has products"
    )
    args = parser.parse_args(argv)

    with get_session_factory()() as session:
        if args.if_empty and not catalog_is_empty(session):
            print("Catalog already loaded: skipping ingest (--if-empty).")
            return 0
        try:
            report = ingest_file(session, args.path, reset_inventory=args.reset)
        except DatasetError as error:
            print(f"Ingest failed: {error}", file=sys.stderr)
            return 1

    report.write(args.report)
    print(report.summary())
    print(f"Report written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
