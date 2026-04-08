"""
Parser for Tata AIG General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 4 pages.
  Page 1 (CY, Dec 2025): 3 tables
    T0 — top section: fire, marine_cargo, marine_hull, total_marine,
          motor_od, motor_tp, total_motor, health, personal_accident,
          travel_insurance, total_health  (10r x 23c)
    T1 — stub header only (2r) — skipped (no row_metrics)
    T2 — channel section (17r x 23c)

  Page 2 (CY, Dec 2025): 4 tables
    T0 — garbled title row (1r, skipped)
    T1 — top section: wc_el, public_product_liability, engineering,
          aviation, crop_insurance, credit_insurance, other_miscellaneous,
          total_miscellaneous, grand_total  (10r x 19c)
    T2 — stub header only (2r) — skipped
    T3 — channel section (16r x 19c)

  Pages 3 & 4 — PY equivalents of pages 1 & 2 (Dec 2024).

CY/PY: detect_calendar_year on top tables gives 2025 (P1/P2) and 2024 (P3/P4).
Max year = CY.

Channel tables: no LOB headers. lob_cols reused from corresponding top table.
detect_row_metrics on channel tables requires start_in_channel_section=True
(default detection picks up false 'distribution_fees'/'rewards' from number cells).
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

_FALLBACK_NAME = "Tata AIG General Insurance Company Limited"


def parse_tata_aig(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Tata AIG NL-6 PDF: {pdf_path}")
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

    # Collect (cal_year, top_table, channel_table, lob_cols, rm_top) across all pages
    groups = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            tables = page.extract_tables()
            i = 0
            while i < len(tables):
                t = tables[i]
                lob_cols = detect_lob_columns(t)
                if not lob_cols:
                    i += 1
                    continue
                rm_top = detect_row_metrics(t)
                if not rm_top:
                    # stub header table (2 rows, no data) — skip
                    i += 1
                    continue
                # Find the channel table immediately following
                ch_t = None
                for k in range(i + 1, min(i + 3, len(tables))):
                    rm_ch = detect_row_metrics(tables[k], start_in_channel_section=True)
                    if rm_ch:
                        ch_t = tables[k]
                        i = k + 1
                        break
                else:
                    i += 1
                groups.append((detect_calendar_year(t), t, ch_t, lob_cols, rm_top))

    if not groups:
        logger.warning("Tata AIG: no valid table groups found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [g[0] for g in groups if g[0] is not None]
    max_year = max(years) if years else None

    for cal_year, top_t, ch_t, lob_cols, rm_top in groups:
        period_data = cy if (max_year and cal_year and cal_year >= max_year) else py

        extract_grid(top_t, rm_top, lob_cols, period_data)

        if ch_t is not None:
            rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
            if rm_ch:
                extract_grid(ch_t, rm_ch, lob_cols, period_data)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
