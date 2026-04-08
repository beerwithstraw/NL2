"""
Parser for The New India Assurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 page, 3 tables.
  T0 — title/header row (2r x 3c) — skipped
  T1 — CY (calendar year 2025): 23 rows x 37 cols
  T2 — PY (calendar year 2024): 23 rows x 37 cols

Both T1 and T2 share identical column layout (confirmed: motor_od at col 9 in both).
T1's LOB header row is garbled (only 5 LOBs detected). T2's header is clean (18 LOBs).
Fix: detect lob_cols from T2 and reuse for T1.

Channel section: boundary row present in both T1/T2 (row 6: "Break-up of the expenses").
detect_row_metrics handles the section split automatically — no separate channel table.

LOBs (18): fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp,
  total_motor, health, personal_accident, total_health, wc_el,
  public_product_liability, engineering, aviation, crop_insurance,
  other_miscellaneous, total_miscellaneous, grand_total.
  (No travel_insurance column in this PDF.)
"""

import logging
from pathlib import Path

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_lob_columns,
    detect_row_metrics,
    detect_calendar_year,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "The New India Assurance Company Limited"


def parse_new_india(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing New India NL-6 PDF: {pdf_path}")
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
            # Find the two data tables (skip any title tables with < 10 rows)
            data_tables = [t for t in tables if t and len(t) >= 10]
            if len(data_tables) < 2:
                logger.warning(f"New India: expected 2 data tables, got {len(data_tables)}")
                continue

            t1, t2 = data_tables[0], data_tables[1]

            # T2 has clean LOB headers — reuse for both
            lob_cols = detect_lob_columns(t2)
            if not lob_cols:
                logger.warning("New India: failed to detect LOB columns from T2")
                continue

            cy_yr = detect_calendar_year(t1)
            py_yr = detect_calendar_year(t2)
            max_yr = max(y for y in [cy_yr, py_yr] if y is not None) if any([cy_yr, py_yr]) else None

            for table, yr in [(t1, cy_yr), (t2, py_yr)]:
                period_data = cy if (max_yr and yr and yr >= max_yr) else py
                rm = detect_row_metrics(table)
                if rm:
                    extract_grid(table, rm, lob_cols, period_data)

                # Row 18: blank col-0 label — pdfplumber drops it, so detect_row_metrics
                # skips it. Positionally it is the last channel before TOTAL = other_channels.
                if len(table) > 18:
                    row = table[18]
                    for lob, qc, yc in lob_cols:
                        qv = clean_number(row[qc]) if qc < len(row) else None
                        yv = clean_number(row[yc]) if yc is not None and yc < len(row) else None
                        if qv is None and yv is None:
                            continue
                        if lob not in period_data.data:
                            period_data.data[lob] = {}
                        if "other_channels" not in period_data.data[lob]:
                            period_data.data[lob]["other_channels"] = {"qtr": None, "ytd": None}
                        if qv is not None and period_data.data[lob]["other_channels"]["qtr"] is None:
                            period_data.data[lob]["other_channels"]["qtr"] = qv
                        if yv is not None and period_data.data[lob]["other_channels"]["ytd"] is None:
                            period_data.data[lob]["other_channels"]["ytd"] = yv

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
