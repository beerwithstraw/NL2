"""
Parser for United India Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 page, 4 tables.
  T0 — CY top section: all 21 LOBs in a single 41-col table (includes other_segments)
  T1 — CY channel section (no LOB headers, separate table)
  T2 — PY top section: same layout
  T3 — PY channel section

CY/PY: detect_calendar_year on T0/T2 gives 2025/2024. Max year = CY.

Note: commission_remuneration / rewards / distribution_fees rows exist in the
table but all data cells are blank — only gross_commission onward has values.
extract_grid handles None values naturally.

Indian number format (1,40,059) handled by clean_number.
"""

import logging
from pathlib import Path

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_lob_columns,
    detect_row_metrics,
    detect_calendar_year,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "United India Insurance Company Limited"


def parse_united_india(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing United India NL-6 PDF: {pdf_path}")
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
            if len(tables) < 4:
                logger.warning(f"United India: expected 4 tables, got {len(tables)}")
                continue

            t0, t1, t2, t3 = tables[0], tables[1], tables[2], tables[3]

            # CY/PY from calendar year in period headers
            cy_yr = detect_calendar_year(t0)
            py_yr = detect_calendar_year(t2)
            max_yr = max(y for y in [cy_yr, py_yr] if y is not None) if any([cy_yr, py_yr]) else None

            for top_t, ch_t, yr in [(t0, t1, cy_yr), (t2, t3, py_yr)]:
                period_data = cy if (max_yr and yr and yr >= max_yr) else py

                lob_cols = detect_lob_columns(top_t)
                if not lob_cols:
                    continue

                rm_top = detect_row_metrics(top_t)
                if rm_top:
                    extract_grid(top_t, rm_top, lob_cols, period_data)

                rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
                if rm_ch:
                    extract_grid(ch_t, rm_ch, lob_cols, period_data)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
