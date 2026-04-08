"""
Parser for IFFCO Tokio General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 8 pages.
  P0: CY summary  (NL-6 header) — fire, total_marine, total_miscellaneous, grand_total
                   qtr cols 1-4, ytd cols 5-8
  P1: PY summary  (no header)   — same column layout, Dec 2024 dates
  P2: CY marine   (NL-6-A)      — marine_cargo, marine_hull, total_marine
                   qtr cols 1-3, ytd cols 4-6
  P3: PY marine   (no header)   — same layout
  P4: CY qtr misc (NL-6-B)      — 14 misc LOBs, single period, cols 1-14
  P5: CY ytd misc (no header)   — same columns
  P6: PY qtr misc (no header)   — same columns
  P7: PY ytd misc (no header)   — same columns

get_nl6_pages() is bypassed here because it filters to header pages only (P0, P2, P4),
missing PY and secondary period pages. pdf.pages used directly instead.

Row labels in col 0. detect_row_metrics handles row detection.
Aviation and crop_insurance are all dashes → absent from output.
"""

import logging
from pathlib import Path
from typing import List, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    resolve_company_name,
    detect_row_metrics,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "IFFCO Tokio General Insurance Company Limited"

# Summary pages (P0=CY, P1=PY): (lob, qtr_col, ytd_col)
_SUMMARY_LOBS: List[Tuple[str, int, int]] = [
    ("fire",                1, 5),
    ("total_marine",        2, 6),
    ("total_miscellaneous", 3, 7),
    ("grand_total",         4, 8),
]

# Marine detail pages (P2=CY, P3=PY): (lob, qtr_col, ytd_col)
_MARINE_LOBS: List[Tuple[str, int, int]] = [
    ("marine_cargo", 1, 4),
    ("marine_hull",  2, 5),
    ("total_marine", 3, 6),
]

# Misc detail pages (P4=CY qtr, P5=CY ytd, P6=PY qtr, P7=PY ytd): (col, lob)
_MISC_LOBS: List[Tuple[int, str]] = [
    (1,  "motor_od"),
    (2,  "motor_tp"),
    (3,  "total_motor"),
    (4,  "engineering"),
    (5,  "aviation"),
    (6,  "wc_el"),
    (7,  "public_product_liability"),
    (8,  "personal_accident"),
    (9,  "health"),
    (10, "travel_insurance"),
    (11, "total_health"),
    (12, "crop_insurance"),
    (13, "other_miscellaneous"),
    (14, "total_miscellaneous"),
]


def _process_paired(table, period_data: PeriodData,
                    lob_map: List[Tuple[str, int, int]]) -> None:
    """Extract metrics from a paired-column (qtr+ytd) table."""
    if not table:
        return
    row_metrics = detect_row_metrics(table)
    if not row_metrics:
        return
    for lob, qc, yc in lob_map:
        for r_idx, metric in row_metrics.items():
            if r_idx >= len(table):
                continue
            row = table[r_idx]
            qv = clean_number(row[qc]) if qc < len(row) else None
            yv = clean_number(row[yc]) if yc < len(row) else None
            if qv is None and yv is None:
                continue
            if lob not in period_data.data:
                period_data.data[lob] = {}
            if metric not in period_data.data[lob]:
                period_data.data[lob][metric] = {"qtr": None, "ytd": None}
            if qv is not None:
                period_data.data[lob][metric]["qtr"] = qv
            if yv is not None:
                period_data.data[lob][metric]["ytd"] = yv


def _process_single(table, period_data: PeriodData,
                    lob_cols: List[Tuple[int, str]], slot: str) -> None:
    """Extract metrics from a single-period table into the given slot (qtr/ytd)."""
    if not table:
        return
    row_metrics = detect_row_metrics(table)
    if not row_metrics:
        return
    for col, lob in lob_cols:
        for r_idx, metric in row_metrics.items():
            if r_idx >= len(table):
                continue
            row = table[r_idx]
            val = clean_number(row[col]) if col < len(row) else None
            if val is None:
                continue
            if lob not in period_data.data:
                period_data.data[lob] = {}
            if metric not in period_data.data[lob]:
                period_data.data[lob][metric] = {"qtr": None, "ytd": None}
            if period_data.data[lob][metric][slot] is None:
                period_data.data[lob][metric][slot] = val


def parse_iffco_tokio(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing IFFCO Tokio NL-6 PDF: {pdf_path}")
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
        pages = list(pdf.pages)
        n = len(pages)
        logger.info(f"IFFCO Tokio: {n} PDF pages")

        def get_tables(idx):
            if idx >= n:
                return []
            return [t for t in pages[idx].extract_tables() if t and len(t) > 3]

        # Summary pages
        for t in get_tables(0):
            _process_paired(t, cy, _SUMMARY_LOBS)
        for t in get_tables(1):
            _process_paired(t, py, _SUMMARY_LOBS)

        # Marine detail pages
        for t in get_tables(2):
            _process_paired(t, cy, _MARINE_LOBS)
        for t in get_tables(3):
            _process_paired(t, py, _MARINE_LOBS)

        # Misc detail pages (one period per page)
        for t in get_tables(4):
            _process_single(t, cy, _MISC_LOBS, "qtr")
        for t in get_tables(5):
            _process_single(t, cy, _MISC_LOBS, "ytd")
        for t in get_tables(6):
            _process_single(t, py, _MISC_LOBS, "qtr")
        for t in get_tables(7):
            _process_single(t, py, _MISC_LOBS, "ytd")

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
