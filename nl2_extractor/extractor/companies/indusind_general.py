"""
Parser for IndusInd General Insurance Company Limited
(formerly Reliance General Insurance Company Limited).

PDF Structure: 1 NL-6 page, 4 tables.
  T0 = CY top section  (12 rows × 39 cols, LOB headers in row 1, year hint 2025)
  T1 = CY channel      (16 rows × 39 cols, no boundary row, no LOB header)
  T2 = PY top section  (10 rows × 39 cols, LOB headers in row 1, year hint 2024)
  T3 = PY channel      (16 rows × 39 cols, no boundary row, no LOB header)

LOBs (19): fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp,
  total_motor, health, personal_accident, travel_insurance, total_health, wc_el,
  public_product_liability, engineering, aviation, crop_insurance,
  other_miscellaneous, total_miscellaneous, grand_total.

lob_cols detected from T0/T2 header rows and reused for T1/T3 (same column layout).
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

_FALLBACK_NAME = "IndusInd General Insurance Company Limited"


def parse_indusind_general(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing IndusInd General PDF: {pdf_path}")
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
            tables = [t for t in page.extract_tables() if t and len(t) >= 4]
            if len(tables) < 4:
                logger.warning(f"IndusInd: expected 4 tables, got {len(tables)}")
                continue

            # (top_table_idx, channel_table_idx, period_data)
            for top_idx, ch_idx, pd in [(0, 1, cy), (2, 3, py)]:
                top_t = tables[top_idx]
                ch_t  = tables[ch_idx]

                lob_cols = merge_lob_header_rows(top_t)
                if not lob_cols:
                    logger.warning(f"IndusInd: no LOB cols in T{top_idx}")
                    continue

                rm_top = detect_row_metrics(top_t)
                if rm_top:
                    extract_grid(top_t, rm_top, lob_cols, pd)

                rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
                if rm_ch:
                    extract_grid(ch_t, rm_ch, lob_cols, pd)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
