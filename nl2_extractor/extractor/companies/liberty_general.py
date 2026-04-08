"""
Parser for Liberty General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 4 pages, 4 tables each.
  T0: CY top section (qtr+ytd columns per LOB)
  T1: CY channel section — start_in_channel_section=True
  T2: PY top section (qtr+ytd columns per LOB)
  T3: PY channel section — start_in_channel_section=True

  Page 1: fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp, total_motor
  Page 2: health, personal_accident, travel_insurance, total_health
  Page 3: wc_el, public_product_liability, engineering, aviation, crop_insurance
  Page 4: other_segments, other_miscellaneous, total_miscellaneous, grand_total

Column layout (T0/T2): col 0 = label, then LOB pairs (odd=qtr, even=ytd).
  detect_lob_columns() resolves all LOBs correctly.

CY/PY: period labels use "Dec-25"/"Dec-24" (2-digit year).
  detect_period_year and detect_calendar_year both return None.
  _detect_year_2digit() parses the suffix → 2025/2024.
  Max year → CY; lower → PY.

Channel: separate table (T1/T3), detect_row_metrics(start_in_channel_section=True).
  lob_cols reused from adjacent top table.

grand_total ytd: absent from page 4 — the rightmost column falls outside
  pdfplumber's table bbox due to a missing right border line. Accepted as null.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_lob_columns,
    detect_row_metrics,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Liberty General Insurance Company Limited"
_YEAR_2DIG_RE = re.compile(r'\b(\d{2})\s*$')


def _detect_year_2digit(table) -> Optional[int]:
    """Parse 2-digit year suffix from period label row (e.g. 'Dec-25' → 2025)."""
    if not table or len(table) < 2:
        return None
    for cell in table[1]:
        if not cell:
            continue
        m = _YEAR_2DIG_RE.search(cell.replace("\n", " ").strip())
        if m:
            yr = int(m.group(1))
            return 2000 + yr
    return None


def parse_liberty_general(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Liberty General NL-6 PDF: {pdf_path}")
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

            lob_cols_cy = detect_lob_columns(t0)
            lob_cols_py = detect_lob_columns(t2)

            if not lob_cols_cy or not lob_cols_py:
                continue

            yr_cy = _detect_year_2digit(t0)
            yr_py = _detect_year_2digit(t2)
            page_data.append((yr_cy, yr_py, t0, t1, lob_cols_cy, t2, t3, lob_cols_py))

    if not page_data:
        logger.warning("Liberty General: no valid pages found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    # Max year = CY
    all_years = [y for d in page_data for y in (d[0], d[1]) if y is not None]
    max_year = max(all_years) if all_years else None

    for yr_cy, yr_py, t0, t1, lob_cols_cy, t2, t3, lob_cols_py in page_data:
        pd_cy = cy if (max_year and yr_cy and yr_cy >= max_year) else py
        pd_py = cy if (max_year and yr_py and yr_py >= max_year) else py

        rm0 = detect_row_metrics(t0)
        if rm0:
            extract_grid(t0, rm0, lob_cols_cy, pd_cy)
        rm1 = detect_row_metrics(t1, start_in_channel_section=True)
        if rm1:
            extract_grid(t1, rm1, lob_cols_cy, pd_cy)

        rm2 = detect_row_metrics(t2)
        if rm2:
            extract_grid(t2, rm2, lob_cols_py, pd_py)
        rm3 = detect_row_metrics(t3, start_in_channel_section=True)
        if rm3:
            extract_grid(t3, rm3, lob_cols_py, pd_py)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
