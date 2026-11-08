"""Ingest report: what was read, rejected, loaded, plus data-quality findings."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Issue(BaseModel):
    sheet: str
    row: int | None = None  # Excel row number (header = row 1)
    key: str | None = None
    message: str


class SheetStats(BaseModel):
    read: int = 0
    valid: int = 0
    rejected: int = 0


class TableStats(BaseModel):
    rows: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0  # existing rows left untouched (inventory without --reset)


class IngestReport(BaseModel):
    dataset: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reset_inventory: bool = False
    sheets: dict[str, SheetStats] = Field(default_factory=dict)
    tables: dict[str, TableStats] = Field(default_factory=dict)
    rejected: list[Issue] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)

    def sheet(self, name: str) -> SheetStats:
        return self.sheets.setdefault(name, SheetStats())

    def reject(self, sheet: str, row: int | None, key: str | None, message: str) -> None:
        self.rejected.append(Issue(sheet=sheet, row=row, key=key, message=message))
        self.sheet(sheet).rejected += 1

    def warn(self, sheet: str, row: int | None, key: str | None, message: str) -> None:
        self.warnings.append(Issue(sheet=sheet, row=row, key=key, message=message))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False))

    def summary(self) -> str:
        lines = [f"Ingest of {self.dataset}"]
        lines.append(f"{'sheet':<16}{'read':>7}{'valid':>7}{'rejected':>10}")
        for name, s in self.sheets.items():
            lines.append(f"{name:<16}{s.read:>7}{s.valid:>7}{s.rejected:>10}")
        lines.append(f"{'table':<20}{'rows':>7}{'inserted':>10}{'updated':>9}{'skipped':>9}")
        for name, t in self.tables.items():
            lines.append(f"{name:<20}{t.rows:>7}{t.inserted:>10}{t.updated:>9}{t.skipped:>9}")
        lines.append(f"warnings: {len(self.warnings)}  rejected rows: {len(self.rejected)}")
        for key, value in self.findings.items():
            shown = len(value) if isinstance(value, list) else value
            lines.append(f"  {key}: {shown}")
        return "\n".join(lines)
