"""
Parser for SBI General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 NL-6 page, 4 tables.
  T0 — title row (2r x 1c) — skipped
  T1 — Fire + Marine + Total Miscellaneous + Grand Total  (24r x 11c)
  T2 — Miscellaneous sub-LOBs part 1: Motor OD/TP/Total, WC, Public Liability,
        Engineering, Aviation  (24r x 15c)
  T3 — Miscellaneous sub-LOBs part 2: Personal Accident, Health, Travel,
        Total Health, Weather & Crop, Others, Total Miscellaneous  (24r x 15c)

CY/PY layout: each table contains BOTH periods in alternating columns.
  Odd cols (1,3,5,...) = CY (period ended 31st Dec 2025)
  Even cols (2,4,6,...) = PY (period ended 31st Dec 2024)

Only YTD values present — no separate quarterly figure.

T1 LOB columns hardcoded — pdfplumber garbles the 2-row marine sub-header.
  "Others" (col 5-6) = marine_hull equivalent for SBI General.
  cols 7-8 = Total Miscellaneous (matches T3 col 13-14 values).

T2/T3: 2-row LOB header — merge_lob_header_rows() handles correctly.

T3 channel section: r7 is a blank "Individual Agents" separator row (skip),
  real Individual Agents data is at r8.

Section boundary:
  T1/T2 r7 = "Channel wise break-up of Commission (Gross)" → detect_row_metrics works.
  T3 has no boundary row → top metrics filtered to rows ≤6, channel uses
  start_in_channel_section=True with r7 blank-row fix.
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
    merge_lob_header_rows,
    detect_row_metrics,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "SBI General Insurance Company Limited"

# T1 LOB columns — hardcoded; pdfplumber garbles the 2-row marine sub-header.
# Format: (lob_key, cy_col, py_col)
_T1_LOB_COLS: List[Tuple[str, int, int]] = [
    ("fire",                1,  2),
    ("marine_cargo",        3,  4),
    ("marine_hull",         5,  6),
    ("total_miscellaneous", 7,  8),
    ("grand_total",         9,  10),
]


def _store(period_data: PeriodData, lob: str, metric: str, val) -> None:
    if val is None:
        return
    if lob not in period_data.data:
        period_data.data[lob] = {}
    if metric not in period_data.data[lob]:
        period_data.data[lob][metric] = {"qtr": None, "ytd": None}
    if period_data.data[lob][metric]["ytd"] is None:
        period_data.data[lob][metric]["ytd"] = val


def _extract_sbi_grid(
    table,
    row_metrics: Dict[int, str],
    lob_cols: List[Tuple[str, int, int]],
    cy: PeriodData,
    py: PeriodData,
) -> None:
    """Extract CY (odd col) and PY (even col) from a single-period-pair SBI table."""
    for row_idx, metric in row_metrics.items():
        if row_idx >= len(table):
            continue
        row = table[row_idx]
        for lob, cy_col, py_col in lob_cols:
            cy_val = clean_number(row[cy_col]) if cy_col < len(row) else None
            py_val = clean_number(row[py_col]) if py_col < len(row) else None
            _store(cy, lob, metric, cy_val)
            _store(py, lob, metric, py_val)


def parse_sbi_general(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing SBI General NL-6 PDF: {pdf_path}")
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
            tables = page.extract_tables()

            # T1: 11-col — hardcoded LOB cols; section boundary at r7
            for table in tables:
                if not table or len(table) < 5:
                    continue
                ncols = len(table[0])

                if ncols == 11:
                    rm = detect_row_metrics(table)
                    if rm:
                        _extract_sbi_grid(table, rm, _T1_LOB_COLS, cy, py)

                elif ncols == 15:
                    lob_cols = merge_lob_header_rows(table)
                    if not lob_cols:
                        continue

                    # Check if T2 (has boundary at r7) or T3 (no boundary)
                    has_boundary = any(
                        "channel wise" in (table[r][0] or "").lower()
                        for r in range(min(9, len(table)))
                    )

                    if has_boundary:
                        # T2: detect_row_metrics handles boundary correctly
                        rm = detect_row_metrics(table)
                    else:
                        # T3: no boundary row — build metrics manually
                        # Top section: rows ≤6 only (r3-r6 are the 4 top metrics)
                        rm_top = {
                            r: m for r, m in detect_row_metrics(table).items()
                            if r <= 6
                        }
                        # Channel section: fix blank r7 separator — r7 grabs 'agent'
                        # but has no data; real agent data is at r8
                        rm_ch = detect_row_metrics(table, start_in_channel_section=True)
                        if 7 in rm_ch and rm_ch[7] == "agent":
                            rm_ch.pop(7)
                            rm_ch[8] = "agent"
                        rm = {**rm_top, **rm_ch}

                    if rm:
                        _extract_sbi_grid(table, rm, lob_cols, cy, py)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
