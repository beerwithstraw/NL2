"""
Parser for National Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 3 pages, 4 tables per page.
  T0 — CY top section     T1 — CY channel section
  T2 — PY top section     T3 — PY channel section

LOBs split across pages:
  Page 1: fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp, total_motor, health
          + personal_accident qtr at col 17 (no ytd col — table ends)
  Page 2: [personal_accident ytd at col 1], travel_insurance, total_health, wc_el,
          public_product_liability, engineering, aviation, crop_insurance, other_segments
  Page 3: other_miscellaneous, total_miscellaneous, grand_total

personal_accident cross-page stitch:
  - General: detect_lob_columns finds personal_accident only if cols 17-18 both exist.
    Page 1 table has 18 cols (0-17), so col 17 exists (qtr) but col 18 does not (ytd=None).
    detect_lob_columns won't find it — hardcoded stitch injects qtr from page 1 col 17.
  - Fallback: page 2 T0 col 1 = personal_accident ytd (confirmed from period header).
    After extraction, if personal_accident ytd is None, inject from page 2 col 1.

Channel tables: no LOB headers — lob_cols reused from corresponding top table.
P1 T1 channel: rows start at index 1 (row 0 is blank) — rm handles this.
"""

import logging
from pathlib import Path
from typing import Dict, Optional

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
from extractor.normaliser import clean_number

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "National Insurance Company Limited"

# personal_accident: qtr at col 17 of page 1 top table (hardcoded — no header in row 0)
_PA_QTR_COL = 17
# personal_accident: ytd at col 1 of page 2 top table (cross-page stitch)
_PA_YTD_COL = 1


def _inject_pa_qtr(table: list, rm: Dict[int, str], period_data: PeriodData) -> None:
    """Inject personal_accident qtr values from col 17 of page 1 top table."""
    for row_idx, metric in rm.items():
        if row_idx >= len(table):
            continue
        row = table[row_idx]
        if len(row) <= _PA_QTR_COL:
            continue
        val = clean_number(row[_PA_QTR_COL])
        if val is None:
            continue
        if "personal_accident" not in period_data.data:
            period_data.data["personal_accident"] = {}
        if metric not in period_data.data["personal_accident"]:
            period_data.data["personal_accident"][metric] = {"qtr": None, "ytd": None}
        if period_data.data["personal_accident"][metric]["qtr"] is None:
            period_data.data["personal_accident"][metric]["qtr"] = val


def _inject_pa_ytd(table: list, rm: Dict[int, str], period_data: PeriodData) -> None:
    """Inject personal_accident ytd values from col 1 of page 2 top table."""
    for row_idx, metric in rm.items():
        if row_idx >= len(table):
            continue
        row = table[row_idx]
        if len(row) <= _PA_YTD_COL:
            continue
        val = clean_number(row[_PA_YTD_COL])
        if val is None:
            continue
        if "personal_accident" not in period_data.data:
            period_data.data["personal_accident"] = {}
        if metric not in period_data.data["personal_accident"]:
            period_data.data["personal_accident"][metric] = {"qtr": None, "ytd": None}
        if period_data.data["personal_accident"][metric]["ytd"] is None:
            period_data.data["personal_accident"][metric]["ytd"] = val


def parse_national_insurance(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing National Insurance NL-6 PDF: {pdf_path}")
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
        for page_idx, page in enumerate(pages):
            tables = page.extract_tables()
            if len(tables) < 4:
                continue

            t0, t1, t2, t3 = tables[0], tables[1], tables[2], tables[3]

            # CY/PY assignment from calendar year in top tables
            cy_yr = detect_calendar_year(t0)
            py_yr = detect_calendar_year(t2)
            max_yr = max((y for y in [cy_yr, py_yr] if y is not None), default=None)

            for top_t, ch_t, yr, period_data in [
                (t0, t1, cy_yr, cy),
                (t2, t3, py_yr, py),
            ]:
                is_cy = (max_yr is not None and yr is not None and yr >= max_yr)
                period_data = cy if is_cy else py

                lob_cols = detect_lob_columns(top_t)
                rm_top = detect_row_metrics(top_t)

                if lob_cols and rm_top:
                    extract_grid(top_t, rm_top, lob_cols, period_data)

                # Page 1: inject personal_accident qtr from col 17
                if page_idx == 0 and rm_top:
                    _inject_pa_qtr(top_t, rm_top, period_data)

                # Page 2: inject personal_accident ytd from col 1
                if page_idx == 1 and rm_top:
                    _inject_pa_ytd(top_t, rm_top, period_data)

                # Channel table: reuse lob_cols from top table
                if lob_cols:
                    rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
                    if rm_ch:
                        extract_grid(ch_t, rm_ch, lob_cols, period_data)

                    # Channel also needs personal_accident stitch
                    if page_idx == 0:
                        _inject_pa_qtr(ch_t, rm_ch, period_data)
                    if page_idx == 1:
                        _inject_pa_ytd(ch_t, rm_ch, period_data)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
