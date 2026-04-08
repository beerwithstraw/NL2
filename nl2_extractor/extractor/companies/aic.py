"""
Parser for Agriculture Insurance Company of India Limited.

PDF Structure: 1 NL-6 page, 4 tables.
  T0 = CY top section  (labels col 0, 12 rows × 11 cols)
  T1 = CY channel      (labels col 0, 16 rows × 11 cols, no boundary row)
  T2 = PY top section  (labels col 0, 10 rows × 11 cols)
  T3 = PY channel      (labels col 0, 16 rows × 11 cols, no boundary row)

Column layout (same across all 4 tables):
  col 0: row labels
  cols 1-2:  Crop Insurance       (qtr=1, ytd=2)
  cols 3-4:  Other Segments       (qtr=3, ytd=4)
  cols 5-6:  Other Miscellaneous  (qtr=5, ytd=6)
  cols 7-8:  Total Miscellaneous  (qtr=7, ytd=8)
  cols 9-10: Grand Total          (qtr=9, ytd=10)
"""

import logging
from pathlib import Path
from typing import List, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_row_metrics,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Agriculture Insurance Company of India Limited"

_LOB_MAP: List[Tuple[str, int, int]] = [
    ("crop_insurance",      1,  2),
    ("other_segments",      3,  4),
    ("other_miscellaneous", 5,  6),
    ("total_miscellaneous", 7,  8),
    ("grand_total",         9,  10),
]


def parse_aic(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing AIC PDF: {pdf_path}")
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
            tables = [t for t in page.extract_tables() if t and len(t) >= 4]

            # Tables come in pairs: (top_section, channel) for CY then PY
            for pair_idx, period_data in enumerate([(cy, 0), (py, 2)]):
                pd, base = period_data
                if base >= len(tables):
                    continue

                top_table = tables[base]
                ch_table  = tables[base + 1] if base + 1 < len(tables) else None

                rm = detect_row_metrics(top_table)
                if rm:
                    extract_grid(top_table, rm, _LOB_MAP, pd)

                if ch_table:
                    rm_ch = detect_row_metrics(ch_table, start_in_channel_section=True)
                    if rm_ch:
                        extract_grid(ch_table, rm_ch, _LOB_MAP, pd)

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
