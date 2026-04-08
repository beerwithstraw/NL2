"""
Parser for Go Digit General Insurance Limited.

PDF Structure: 3 NL-6 pages, 2 tables per page (T0=CY, T1=PY).
  Page 0: fire, marine_cargo, marine_hull, total_marine,
          motor_od, motor_tp, total_motor
  Page 1: health, personal_accident, travel_insurance, total_health,
          wc_el, public_product_liability, engineering
  Page 2: aviation, crop_insurance, other_miscellaneous,
          total_miscellaneous, grand_total

Each table: 29 rows × 15 or 11 cols.
  Row 0: category span headers ("FIRE", "Marine Cargo", "Miscellaneous"...)
  Row 1: sub-LOB headers under spans ("Motor OD", "Motor TP", ...)
  Row 2: period headers ("For the Quarter December 2025" / "Up to...")
  Rows 3+: data rows (section boundary present at row 11)

Two-row LOB header issue: detect_lob_columns only reads one header row.
Fix: merge rows 0+1 — fill empty cells in row 0 with values from row 1.
This gives a single flat header row with all LOB names.

Year hint: period headers say "December 2025/2024" — no YYYY-YY pattern,
so detect_period_year returns None. CY/PY assigned by table position:
even positions (0,2,4) = CY, odd (1,3,5) = PY.
"""

import logging
from pathlib import Path
from typing import List, Tuple, Optional

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_lob_columns,
    detect_row_metrics,
    extract_grid,
    match_header,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Go Digit General Insurance Limited"


def _merge_header_rows(table: list) -> Optional[List[Tuple[str, int, int]]]:
    """
    Build LOB columns by merging rows 0 and 1.
    Empty cells in row 0 are filled from row 1 so sub-LOBs under
    spanning category headers are visible to detect_lob_columns.
    Row 2 is used as the period row (qtr/ytd detection).
    """
    if len(table) < 3:
        return None

    row0 = list(table[0])
    row1 = table[1]

    # Merge rule:
    #   - Both non-empty → row 0 is a category span, row 1 has the real LOB → use row 1
    #   - Only row 0 non-empty → standalone LOB in row 0 → use row 0
    #   - Only row 1 non-empty → sub-LOB not in row 0 → use row 1
    #   - Both empty → leave empty
    r1 = list(row1) + [""] * max(0, len(row0) - len(row1))
    merged = [
        r1[i] if (cell and cell.strip() and r1[i] and r1[i].strip())
        else (cell if (cell and cell.strip()) else r1[i])
        for i, cell in enumerate(row0)
    ]

    # Build a synthetic 2-row table: [merged_header, period_row, ...]
    synthetic = [merged, table[2]] + list(table[2:])
    return detect_lob_columns(synthetic)


def parse_go_digit(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing Go Digit PDF: {pdf_path}")
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

    position = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            for table in page.extract_tables():
                if not table or len(table) < 5:
                    position += 1
                    continue

                lob_cols = _merge_header_rows(table)
                if not lob_cols:
                    position += 1
                    continue

                rm = detect_row_metrics(table)
                if not rm:
                    position += 1
                    continue

                pd = cy if position % 2 == 0 else py
                extract_grid(table, rm, lob_cols, pd)
                position += 1

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
