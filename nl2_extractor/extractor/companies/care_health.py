"""
Dedicated Parser for Care Health Insurance Company Limited.

PDF Structure (single NL-6 page, 2 tables):
  T0 — top-section metrics (commission_remuneration … net_commission)
  T1 — channel breakdown metrics (agent … total_channel)

Column layout (17 cols, col 0 = row label):
  CY Quarter : cols 1-4   → Health(1), PA(2), Travel(3), Total Health(4)
  CY YTD     : cols 5-8   → Health(5), PA(6), Travel(7), Total Health(8)
  PY Quarter : cols 9-12  → Health(9), PA(10), Travel(11), Total Health(12)
  PY YTD     : cols 13-16 → Health(13), PA(14), Travel(15), Total Health(16)
"""

import logging
from pathlib import Path
from typing import List, Tuple

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    detect_row_metrics,
    resolve_company_name,
)

logger = logging.getLogger(__name__)

# (lob_key, col_offset_within_period_group)
_LOB_OFFSETS: List[Tuple[str, int]] = [
    ("health",            0),
    ("personal_accident", 1),
    ("travel_insurance",  2),
    ("total_health",      3),
    # "Total Health" column = grand_total for this health-only insurer (same data)
    ("grand_total",       3),
]

_CY_QTR_START = 1
_CY_YTD_START = 5
_PY_QTR_START = 9
_PY_YTD_START = 13


def parse_care_health(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    import pdfplumber

    logger.info(f"Parsing Care Health PDF: {pdf_path}")
    company_name = resolve_company_name(company_key, pdf_path, "Care Health Insurance Company Limited")

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
            for table_idx, table in enumerate(page.extract_tables()):
                if not table or len(table) < 2:
                    continue

                # T0 = top section (commission_remuneration … net_commission)
                # T1+ = channel breakdown (no section boundary row present)
                in_channel = table_idx > 0
                row_metrics = detect_row_metrics(table, start_in_channel_section=in_channel)
                if not row_metrics:
                    continue

                for row_idx, metric in row_metrics.items():
                    if row_idx >= len(table):
                        continue
                    row = table[row_idx]

                    for lob, offset in _LOB_OFFSETS:
                        # Current year
                        cy_qc = _CY_QTR_START + offset
                        cy_yc = _CY_YTD_START + offset
                        cy_qv = clean_number(row[cy_qc]) if cy_qc < len(row) else None
                        cy_yv = clean_number(row[cy_yc]) if cy_yc < len(row) else None
                        if cy_qv is not None or cy_yv is not None:
                            if lob not in cy.data:
                                cy.data[lob] = {}
                            if metric not in cy.data[lob]:
                                cy.data[lob][metric] = {"qtr": None, "ytd": None}
                            if cy_qv is not None and cy.data[lob][metric]["qtr"] is None:
                                cy.data[lob][metric]["qtr"] = cy_qv
                            if cy_yv is not None and cy.data[lob][metric]["ytd"] is None:
                                cy.data[lob][metric]["ytd"] = cy_yv

                        # Prior year
                        py_qc = _PY_QTR_START + offset
                        py_yc = _PY_YTD_START + offset
                        py_qv = clean_number(row[py_qc]) if py_qc < len(row) else None
                        py_yv = clean_number(row[py_yc]) if py_yc < len(row) else None
                        if py_qv is not None or py_yv is not None:
                            if lob not in py.data:
                                py.data[lob] = {}
                            if metric not in py.data[lob]:
                                py.data[lob][metric] = {"qtr": None, "ytd": None}
                            if py_qv is not None and py.data[lob][metric]["qtr"] is None:
                                py.data[lob][metric]["qtr"] = py_qv
                            if py_yv is not None and py.data[lob][metric]["ytd"] is None:
                                py.data[lob][metric]["ytd"] = py_yv

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
