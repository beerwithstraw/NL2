"""
Parser for Cholamandalam MS General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 6 pages, 2 tables per page (T0=top, T1=channel).
  Pages 1-3: CY (Dec 2025)
  Pages 4-6: PY (Dec 2024)

  Page 1/4: fire, marine_cargo, marine_hull, total_marine,
             motor_od, motor_tp, total_motor  (15c)
  Page 2/5: health, personal_accident, travel_insurance, total_health,
             wc_el, public_product_liability, engineering  (15c)
  Page 3/6: aviation, crop_insurance, other_segments,
             other_miscellaneous, total_miscellaneous, grand_total  (13c)

Single-row LOB header: detect_lob_columns() detects all LOBs correctly from r0.

CY/PY: detect_calendar_year gives 2025/2024 from T0 on each page.
  Max year = CY, lower year = PY.

Channel: separate table (T1), start_in_channel_section=True.
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

_FALLBACK_NAME = "Cholamandalam MS General Insurance Company Limited"


def parse_chola_ms(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Chola MS NL-6 PDF: {pdf_path}")
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

    page_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            tables = page.extract_tables()
            if len(tables) < 2:
                continue
            t0, t1 = tables[0], tables[1]

            lob_cols = detect_lob_columns(t0)
            if not lob_cols:
                continue

            cal_year = detect_calendar_year(t0)
            page_data.append((cal_year, t0, t1, lob_cols))

    if not page_data:
        logger.warning("Chola MS: no valid pages found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [d[0] for d in page_data if d[0] is not None]
    max_year = max(years) if years else None

    for cal_year, t0, t1, lob_cols in page_data:
        if max_year is not None:
            period_data = cy if (cal_year is not None and cal_year >= max_year) else py
        else:
            period_data = cy

        rm_top = detect_row_metrics(t0)
        if rm_top:
            extract_grid(t0, rm_top, lob_cols, period_data)

        rm_ch = detect_row_metrics(t1, start_in_channel_section=True)
        if rm_ch:
            extract_grid(t1, rm_ch, lob_cols, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
