"""
Parser for ManipalCigna Health Insurance Company Limited.

PDF Structure: 1 NL-6 page, 2 tables.
  T0 = title text (ignored, < 5 rows).
  T1 = single data table, 33 rows × 18 cols — ALL periods in one table.

Column layout:
  col 0: S.No | col 1: Particulars (row labels)
  cols 2-5:   Health Insurance  (CY_qtr=2, CY_ytd=3, PY_qtr=4, PY_ytd=5)
  cols 6-9:   Personal Accident (CY_qtr=6, CY_ytd=7, PY_qtr=8, PY_ytd=9)
  cols 10-13: Travel Insurance  (CY_qtr=10, CY_ytd=11, PY_qtr=12, PY_ytd=13)
  cols 14-17: Total Health      (CY_qtr=14, CY_ytd=15, PY_qtr=16, PY_ytd=17)

Section boundary at row 12: "break-up of the expenses..."
Sub-rows (labels starting with "-") are skipped; parent row holds the sum.
Col 0 has S.No for channel rows, so metric detection reads labels from col 1.
"""

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    _TOP_LABEL_TO_METRIC,
    _CHANNEL_LABEL_TO_METRIC,
    _SKIP_LABELS,
    _SECTION_BOUNDARIES,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "ManipalCigna Health Insurance Company Limited"

# (lob_key, CY_qtr_col, CY_ytd_col, PY_qtr_col, PY_ytd_col)
_LOB_GROUPS: List[Tuple[str, int, int, int, int]] = [
    ("health",            2,  3,  4,  5),
    ("personal_accident", 6,  7,  8,  9),
    ("travel_insurance",  10, 11, 12, 13),
    ("total_health",      14, 15, 16, 17),
    # "TOTAL" column = grand_total for this health-only insurer (same data as total_health)
    ("grand_total",       14, 15, 16, 17),
]


def _detect_metrics_col1(table) -> Dict[int, str]:
    """Row metric detection that reads labels from col 1 (col 0 = S.No)."""
    metrics: Dict[int, str] = {}
    in_channel = False

    for ri, row in enumerate(table):
        if not row or len(row) < 2:
            continue
        label = (row[1] or "").replace("\n", " ").strip().lower()
        if not label or label.startswith("-") or label in _SKIP_LABELS:
            continue
        if any(b in label for b in _SECTION_BOUNDARIES):
            in_channel = True
            continue

        pairs = _CHANNEL_LABEL_TO_METRIC if in_channel else _TOP_LABEL_TO_METRIC
        for pattern, metric_key in pairs:
            if pattern in label and metric_key not in metrics.values():
                metrics[ri] = metric_key
                break

    return metrics


def _store(period_data: PeriodData, lob: str, metric: str, qv, yv) -> None:
    if qv is None and yv is None:
        return
    if lob not in period_data.data:
        period_data.data[lob] = {}
    if metric not in period_data.data[lob]:
        period_data.data[lob][metric] = {"qtr": None, "ytd": None}
    if qv is not None and period_data.data[lob][metric]["qtr"] is None:
        period_data.data[lob][metric]["qtr"] = qv
    if yv is not None and period_data.data[lob][metric]["ytd"] is None:
        period_data.data[lob][metric]["ytd"] = yv


def parse_manipal_cigna(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    import pdfplumber

    logger.info(f"Parsing ManipalCigna PDF: {pdf_path}")
    company_name = resolve_company_name(company_key, pdf_path, _FALLBACK_NAME)

    extract = CompanyExtract(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=company_name,
        form_type="NL6",
        quarter=quarter,
        year=year,
    )

    cy = PeriodData(period_label="current")
    py = PeriodData(period_label="prior")

    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            for table in page.extract_tables():
                if not table or len(table) < 5 or len(table[0]) < 18:
                    continue

                row_metrics = _detect_metrics_col1(table)
                if not row_metrics:
                    continue

                for row_idx, metric in row_metrics.items():
                    if row_idx >= len(table):
                        continue
                    row = table[row_idx]

                    for lob, cy_qc, cy_yc, py_qc, py_yc in _LOB_GROUPS:
                        cy_qv = clean_number(row[cy_qc]) if cy_qc < len(row) else None
                        cy_yv = clean_number(row[cy_yc]) if cy_yc < len(row) else None
                        py_qv = clean_number(row[py_qc]) if py_qc < len(row) else None
                        py_yv = clean_number(row[py_yc]) if py_yc < len(row) else None
                        _store(cy, lob, metric, cy_qv, cy_yv)
                        _store(py, lob, metric, py_qv, py_yv)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
