"""
Parser for Aditya Birla Health Insurance Company Limited.

PDF Structure: 1 NL-6 page, 1 table (62 rows × 11 cols).
  Single table contains two period blocks back-to-back:
    Block 1 (rows ~4-29) : Current Year
    Block 2 (rows ~35-60): Prior Year
  Block boundary detected by the second "Particulars" header row.

Column layout (identical for both blocks):
  col 0: empty | col 1: row labels
  col 2: Health qtr        col 3: Personal Accident qtr
  col 4: Travel qtr        col 5: Total qtr
  col 6: Health ytd        col 7: Personal Accident ytd
  col 8: Travel ytd        col 9: Total ytd

Section boundary "break-up of the expenses" present in each block,
so detect_row_metrics is called per-block (not on the full table) to
ensure in_channel_section resets between the two blocks.
"""

import logging
from pathlib import Path
from typing import List, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_row_metrics,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Aditya Birla Health Insurance Company Limited"

# (lob_key, qtr_col, ytd_col)
_LOB_MAP: List[Tuple[str, int, int]] = [
    ("health",            2, 6),
    ("personal_accident", 3, 7),
    ("travel_insurance",  4, 8),
    ("total_health",      5, 9),
]


def _split_blocks(table: list) -> Tuple[list, list]:
    """Split the table into CY and PY blocks at the second 'Particulars' row."""
    split_at = None
    seen_particulars = 0
    for ri, row in enumerate(table):
        label = (row[1] or "").strip().lower() if len(row) > 1 and row[1] else ""
        if label == "particulars":
            seen_particulars += 1
            if seen_particulars == 2:
                split_at = ri
                break
    if split_at:
        return table[:split_at], table[split_at:]
    return table, []


def parse_aditya_birla_health(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing Aditya Birla Health PDF: {pdf_path}")
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
            for table in page.extract_tables():
                if not table or len(table) < 10:
                    continue

                cy_block, py_block = _split_blocks(table)

                if cy_block:
                    rm = detect_row_metrics(cy_block)
                    if rm:
                        extract_grid(cy_block, rm, _LOB_MAP, cy)

                if py_block:
                    rm = detect_row_metrics(py_block)
                    if rm:
                        extract_grid(py_block, rm, _LOB_MAP, py)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
