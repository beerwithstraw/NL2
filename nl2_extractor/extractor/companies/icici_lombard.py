"""
Parser for ICICI Lombard General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 2 pages.
  Page 1 (CY, Q3 2025-26): 5 tables
    T0 — title row (2 rows x 1 col) — skipped (no LOBs detected)
    T1 — top section: fire, marine_cargo, marine_hull, total_marine,
          motor_od, motor_tp, total_motor, health, personal_accident,
          travel_insurance, total_health
    T2 — channel section (same LOB columns as T1)
    T3 — top section: wc_el, public_product_liability, engineering,
          aviation, crop_insurance, credit_insurance, other_miscellaneous,
          total_miscellaneous, grand_total
    T4 — channel section (same LOB columns as T3)

  Page 2 (PY, Q3 2024-25): 4 tables
    T0/T1 — PY equivalents of T1/T2 above
    T2/T3 — PY equivalents of T3/T4 above

Header structure: single-row LOB headers in row 0. detect_lob_columns works
  directly. Title table is automatically skipped (returns no lob_cols).

Period detection: "For Q3 2025-26" / "For Q3 2024-25" — detect_period_year
  returns 2025 / 2024. Max year → CY.

Channel section: each top table is immediately followed by its channel table
  (no boundary row present in either). Parser pairs them by position.

grand_total columns: both cols 17 and 18 in T3/T2 contain "Grand Total"
  (PDF artefact). detect_lob_columns produces two entries — (17, None) and
  (None, 18) — which extract_grid combines correctly into one qtr+ytd pair.

Note: number cells contain OCR spaces (e.g. "7 ,915", "3 3,165") — handled
  transparently by clean_number.
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
    detect_period_year,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "ICICI Lombard General Insurance Company Limited"


def parse_icici_lombard(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing ICICI Lombard NL-6 PDF: {pdf_path}")
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

    # First pass: collect (period_year, top_table, channel_table, lob_cols)
    groups = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            tables = page.extract_tables()
            i = 0
            while i < len(tables):
                lob_cols = detect_lob_columns(tables[i])
                if not lob_cols:
                    i += 1
                    continue
                # Found a top-section table; next table is its channel section
                top_t = tables[i]
                ch_t  = tables[i + 1] if i + 1 < len(tables) else None
                groups.append((detect_period_year(top_t), top_t, ch_t, lob_cols))
                i += 2  # consume both

    if not groups:
        logger.warning("ICICI Lombard: no valid table groups found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    # CY = max period year
    years = [g[0] for g in groups if g[0] is not None]
    max_year = max(years) if years else None

    for fy, top_t, ch_t, lob_cols in groups:
        period_data = cy if (max_year is not None and fy is not None and fy >= max_year) else py

        rm_top = detect_row_metrics(top_t)
        if rm_top:
            extract_grid(top_t, rm_top, lob_cols, period_data)

        if ch_t is not None:
            rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
            if rm_ch:
                extract_grid(ch_t, rm_ch, lob_cols, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
