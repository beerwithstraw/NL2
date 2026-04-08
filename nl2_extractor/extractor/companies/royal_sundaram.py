"""
Parser for Royal Sundaram General Insurance Co. Limited (NL-6 Commission Schedule).

PDF Structure: 4 pages, 2 tables per page.
  Pages 1-2 (CY, Dec'25): T0=top, T1=channel
  Pages 3-4 (PY, Dec'24): T0=top, T1=channel

  Page 1/3: fire, marine_cargo, marine_hull, total_marine,
             motor_od, motor_tp, total_motor, wc_el, health  (19c)
  Page 2/4: personal_accident, travel_insurance, total_health,
             public_product_liability, engineering, aviation,
             crop_insurance, other_miscellaneous, total_miscellaneous  (19c)

2-row LOB header: row 0 = category span, row 1 = sub-LOB names.
  merge_lob_header_rows() detects all LOBs correctly.

CY/PY: period headers use "Dec'25"/"Dec'24" (2-digit year) which
  detect_calendar_year misses. Assigned by page position: pages 1-2 = CY,
  pages 3-4 = PY.

grand_total: absent from this PDF — accepted.

Channel: separate table (T1), start_in_channel_section=True.
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

_FALLBACK_NAME = "Royal Sundaram General Insurance Co. Limited"


def parse_royal_sundaram(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Royal Sundaram NL-6 PDF: {pdf_path}")
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
        pages = get_nl6_pages(pdf)
        n = len(pages)
        # First half = CY, second half = PY
        cy_pages = pages[:n // 2]
        py_pages = pages[n // 2:]

        for period_data, page_group in [(cy, cy_pages), (py, py_pages)]:
            for page in page_group:
                tables = page.extract_tables()
                if len(tables) < 2:
                    continue
                top_t, ch_t = tables[0], tables[1]

                lob_cols = merge_lob_header_rows(top_t)
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
