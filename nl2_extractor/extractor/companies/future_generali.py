"""
Parser for Future Generali India Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 2 pages, 4 tables each.
  T0: top section, fire→total_health (23c, 11 LOBs × 2 cols)
  T1: channel section for T0 LOBs — start_in_channel_section=True
  T2: top section, wc_el→grand_total (17c, 8 LOBs × 2 cols)
      Grand Total split: col 15=qtr only, col 16=ytd only — extract_grid handles None cols.
  T3: channel section for T2 LOBs — start_in_channel_section=True

2-row LOB header: r0=category span ("Miscellaneous"), r1=sub-LOBs.
  merge_lob_header_rows() resolves all LOBs correctly.

CY/PY: detect_period_year gives 2025 (P0) / 2024 (P1).
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

_FALLBACK_NAME = "Future Generali India Insurance Company Limited"


def parse_future_generali(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Future Generali NL-6 PDF: {pdf_path}")
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
            if len(tables) < 4:
                continue
            t0, t1, t2, t3 = tables[0], tables[1], tables[2], tables[3]

            lob_cols_a = merge_lob_header_rows(t0)
            lob_cols_b = merge_lob_header_rows(t2)
            if not lob_cols_a or not lob_cols_b:
                continue

            yr = detect_period_year(t0)
            page_data.append((yr, t0, t1, lob_cols_a, t2, t3, lob_cols_b))

    if not page_data:
        logger.warning("Future Generali: no valid pages found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [d[0] for d in page_data if d[0] is not None]
    max_year = max(years) if years else None

    for yr, t0, t1, lob_cols_a, t2, t3, lob_cols_b in page_data:
        period_data = cy if (max_year and yr and yr >= max_year) else py

        rm0 = detect_row_metrics(t0)
        if rm0:
            extract_grid(t0, rm0, lob_cols_a, period_data)

        rm1 = detect_row_metrics(t1, start_in_channel_section=True)
        if rm1:
            extract_grid(t1, rm1, lob_cols_a, period_data)

        rm2 = detect_row_metrics(t2)
        if rm2:
            extract_grid(t2, rm2, lob_cols_b, period_data)

        rm3 = detect_row_metrics(t3, start_in_channel_section=True)
        if rm3:
            extract_grid(t3, rm3, lob_cols_b, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
