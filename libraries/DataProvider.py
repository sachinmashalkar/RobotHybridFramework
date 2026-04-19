"""Data-driven helpers: read CSV / JSON / Excel fixtures as Robot data.

These keywords return plain lists/dicts so they compose well with
SeleniumLibrary or RequestsLibrary loops. For suites that want native
data-driven tests, prefer the ``DataDriver`` library with the provided
CSV files in ``testdata/``.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import openpyxl
from robot.api.deco import keyword, library

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTDATA_DIR = REPO_ROOT / "testdata"


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else TESTDATA_DIR / p


@library(scope="GLOBAL", auto_keywords=False)
class DataProvider:
    ROBOT_LIBRARY_VERSION = "1.0.0"

    @keyword("Load Csv Rows")
    def load_csv_rows(self, filename: str) -> list[dict[str, str]]:
        path = _resolve(filename)
        with path.open("r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    @keyword("Load Json Data")
    def load_json_data(self, filename: str) -> dict | list:
        path = _resolve(filename)
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    @keyword("Load Excel Sheet")
    def load_excel_sheet(self, filename: str, sheet: str | None = None) -> list[dict[str, str]]:
        """Read an Excel sheet into a list of dicts keyed by the header row."""
        path = _resolve(filename)
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb[sheet] if sheet else wb.active
        rows = ws.iter_rows(values_only=True)
        try:
            header = [str(c) if c is not None else "" for c in next(rows)]
        except StopIteration:
            return []
        result: list[dict[str, str]] = []
        for row in rows:
            if row is None or all(cell is None for cell in row):
                continue
            result.append({header[i]: ("" if cell is None else str(cell)) for i, cell in enumerate(row)})
        return result
