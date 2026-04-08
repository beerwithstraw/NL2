"""
Parser for The Oriental Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 3 pages, 1 table per page (47 rows x 15/13 cols).
Each table contains CY and PY stacked — split at the second "Particulars" row.

  Page 1: fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp, total_motor
  Page 2: health, personal_accident, travel_insurance, total_health,
          wc_el, [public_product_liability — garbled], engineering
  Page 3: aviation, crop_insurance, other_segments, other_miscellaneous,
          total_miscellaneous, grand_total

CY = first half (rows before 2nd "Particulars"), PY = second half.
Calendar year in PY period headers is garbled ("31.12.24" → 2009 false positive)
so CY/PY is assigned by position, not year detection.

public_product_liability: on page 2 the header cell is OCR-garbled and undetectable.
Fix: after detect_lob_columns, if wc_el present but public_product_liability absent,
inject it at cols 11-12 (confirmed from PDF column layout).

Channel section: boundary row "Break-up of the expenses" present in each half —
detect_row_metrics handles the split automatically.
"""

import logging
from pathlib import Path
from typing import List, Tuple

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

_FALLBACK_NAME = "The Oriental Insurance Company Limited"


def _split_cy_py(table: list) -> Tuple[list, list]:
    """Split a stacked table at the second 'Particulars' row."""
    found_first = False
    for i, row in enumerate(table):
        if row and (row[0] or "").strip() == "Particulars":
            if not found_first:
                found_first = True
            else:
                return table[:i], table[i:]
    return table, []


def _fix_lob_cols_p3(lob_cols: List[Tuple]) -> List[Tuple]:
    """
    Page 3 channel table: two OCR garbling issues.
    1. 'Teonttal Miscellaneous' (garble of 'Total Miscellaneous') contains 'miscellaneous'
       so match_header returns other_miscellaneous for both col 7 and col 9.
       Fix: rename the 2nd other_miscellaneous occurrence to total_miscellaneous.
    2. Grand Total split into two single-period columns (col 11=qtr, col 12=ytd).
       Fix: merge both into one (grand_total, 11, 12) entry.
    """
    fixed = []
    seen_other_misc = False
    gt_qc = gt_yc = None

    for lob, qc, yc in lob_cols:
        if lob == "other_miscellaneous":
            if not seen_other_misc:
                seen_other_misc = True
                fixed.append((lob, qc, yc))
            else:
                fixed.append(("total_miscellaneous", qc, yc))
        elif lob == "grand_total":
            if qc is not None:
                gt_qc = qc
            if yc is not None:
                gt_yc = yc
        else:
            fixed.append((lob, qc, yc))

    if gt_qc is not None or gt_yc is not None:
        fixed.append(("grand_total", gt_qc, gt_yc))

    return fixed


def _fix_lob_cols(lob_cols: List[Tuple], has_page2_lobs: bool) -> List[Tuple]:
    """
    On page 2 the public_product_liability header is OCR-garbled.
    If wc_el is present but public_product_liability is absent, inject at cols 11-12.
    has_page2_lobs: True when lob_cols contains wc_el (i.e., this is page 2).
    """
    lob_names = {l for l, _, _ in lob_cols}
    if has_page2_lobs and "wc_el" in lob_names and "public_product_liability" not in lob_names:
        # Insert after wc_el (which is at cols 9-10) → public_product_liability at 11-12
        result = []
        for entry in lob_cols:
            result.append(entry)
            if entry[0] == "wc_el":
                result.append(("public_product_liability", 11, 12))
        return result
    return lob_cols


def parse_oriental_insurance(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Oriental Insurance NL-6 PDF: {pdf_path}")
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
            if not tables:
                continue
            table = tables[0]

            cy_half, py_half = _split_cy_py(table)
            if not cy_half:
                continue

            for half, period_data in [(cy_half, cy), (py_half, py)]:
                if not half:
                    continue
                lob_cols = detect_lob_columns(half)
                if not lob_cols:
                    continue

                # Detect page identity from lob_names
                lob_names = {l for l, _, _ in lob_cols}
                is_page2 = "wc_el" in lob_names or "health" in lob_names
                is_page3 = "aviation" in lob_names or "crop_insurance" in lob_names
                lob_cols = _fix_lob_cols(lob_cols, is_page2)
                if is_page3:
                    lob_cols = _fix_lob_cols_p3(lob_cols)

                rm = detect_row_metrics(half)
                if rm:
                    extract_grid(half, rm, lob_cols, period_data)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
