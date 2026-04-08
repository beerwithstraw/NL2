"""
Parser for HDFC ERGO General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 2 pages, 4 tables per page.
  Page 1 (CY, Dec 2025):
    T0 — top section: fire, marine_cargo, marine_hull, total_marine,
          motor_od, motor_tp, total_motor, health, personal_accident,
          travel_insurance, total_health  (11r x 23c, 2-row LOB header)
    T1 — channel section (16r x 23c)
    T2 — top section: wc_el, public_product_liability, engineering, aviation,
          crop_insurance, other_liability, home, speciality, other_miscellaneous,
          total_miscellaneous, grand_total  (11r x 23c, 2-row LOB header)
    T3 — channel section (16r x 23c)

  Page 2 (PY, Dec 2024): identical structure.

2-row LOB header: row 0 has category spans, row 1 has sub-LOB names.
  merge_lob_header_rows() handles both T0 and T2 correctly.

CY/PY: detect_calendar_year gives 2025/2024 from T0 on each page. Max year = CY.

RI labels: "Add: Commission on Re- insurance Accepted" / "Less: Commission on
  Re- insurance Ceded" — space in "Re- insurance" added as alias in _base_nl6.py.

HDFC-specific LOBs: other_liability, specialty, home (per company_registry.py).
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
    detect_calendar_year,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "HDFC ERGO General Insurance Company Limited"


def parse_hdfc_ergo(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing HDFC ERGO NL-6 PDF: {pdf_path}")
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

    groups = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            tables = page.extract_tables()
            i = 0
            while i < len(tables):
                t = tables[i]
                lob_cols = merge_lob_header_rows(t)
                if not lob_cols:
                    i += 1
                    continue
                rm_top = detect_row_metrics(t)
                if not rm_top:
                    i += 1
                    continue
                # Channel table follows
                ch_t = None
                if i + 1 < len(tables):
                    rm_ch = detect_row_metrics(tables[i + 1], start_in_channel_section=True)
                    if rm_ch:
                        ch_t = tables[i + 1]
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
                groups.append((detect_calendar_year(t), t, ch_t, lob_cols, rm_top))

    if not groups:
        logger.warning("HDFC ERGO: no valid table groups found")
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
