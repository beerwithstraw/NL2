"""
Parser for Niva Bupa Health Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 NL-6 page, 2 tables. T0=CY, T1=PY.
Each table: 30r x 13c.

2-row LOB header:
  r0: "Miscellaneous" category span — detect_lob_columns sees only this; use
      merge_lob_header_rows to resolve the 6 real LOBs from r1.
  r1: Health, Personal Accident, Travel Insurance,
      Total Health, Total Miscellaneous, Grand Total  (cols 1-12, paired qtr/ytd)

Section boundary "break-up of the expenses" present → detect_row_metrics handles
top-section and channel-section rows automatically.

CY/PY: detect_period_year returns None (period labels use "Sep"/"Mar" without year).
  Assignment by table position: T0=CY, T1=PY.
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
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Niva Bupa Health Insurance Company Limited"


def parse_niva_bupa(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Niva Bupa NL-6 PDF: {pdf_path}")
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
            data_tables = [t for t in tables if t and len(t) > 3]
            # T0=CY, T1=PY (position-based; detect_period_year returns None)
            for ti, t in enumerate(data_tables[:2]):
                period_data = cy if ti == 0 else py
                lob_cols = merge_lob_header_rows(t)
                if not lob_cols:
                    continue
                rm = detect_row_metrics(t)
                if rm:
                    extract_grid(t, rm, lob_cols, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
