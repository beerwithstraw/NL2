"""
Parser for Zuno General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 page, 2 tables.
  T0 = CY (Q3 FY 2025-26)
  T1 = PY (Q3 FY 2024-25)

Both tables contain top section + channel section in the same table.
  r0:  category span (Miscellaneous)
  r1:  LOB names (FIRE, Marine Cargo, … Grand Total) — 20 LOBs × 2 cols each = 41c
  r2:  period sub-headers (For Q3 FY, Upto Q3)
  r3-r9:   top-section metrics
  r10-r12: blank / boundary
  r13-r25: channel-section metrics (T0) / r14-r26 (T1)

merge_lob_header_rows() detects all 20 LOBs correctly.
detect_row_metrics() picks up both top and channel rows in one pass
  (section boundary triggers mid-table).

Grand Total occupies two separate header cells (cols 39 and 40),
  producing two lob_map entries; extract_grid handles None cols correctly.

CY/PY: detect_period_year gives 2025 (T0) / 2024 (T1).
"""

import logging
from pathlib import Path

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    merge_lob_header_rows,
    detect_row_metrics,
    detect_period_year,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Zuno General Insurance Company Limited"


def parse_zuno(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Zuno NL-6 PDF: {pdf_path}")
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

    table_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            for t in page.extract_tables():
                lob_cols = merge_lob_header_rows(t)
                if not lob_cols:
                    continue
                rm = detect_row_metrics(t)
                if not rm:
                    continue
                yr = detect_period_year(t)
                table_data.append((yr, t, lob_cols, rm))

    if not table_data:
        logger.warning("Zuno: no valid tables found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [d[0] for d in table_data if d[0] is not None]
    max_year = max(years) if years else None

    for yr, t, lob_cols, rm in table_data:
        if max_year is not None:
            period_data = cy if (yr is not None and yr >= max_year) else py
        else:
            period_data = cy

        extract_grid(t, rm, lob_cols, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
