"""
Parser for Bajaj Allianz General Insurance Company Limited -- NL-2-B-PL.
(Also filed as "BajajGeneral" in IRDAI submissions.)

PDF Structure (Q3 FY2026):
  1 page, 1 table: 47 rows x 7 cols
  Col 0: Serial number (1, 2, ..., 9) -- skip
  Col 1: Particulars (P&L label)
  Col 2: Schedule Ref. Form No. -- skip
  Col 3: For the quarter ended Dec 2025  -> cy_qtr
  Col 4: Up to the period ended Dec 2025 -> cy_ytd
  Col 5: For the quarter ended Dec 2024  -> py_qtr
  Col 6: Up to the period ended Dec 2024 -> py_ytd

Standard single-table layout -- parse_header_driven_nl2() handles it directly.
"""

import logging
from extractor.companies._base_nl2 import parse_header_driven_nl2

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Bajaj Allianz General Insurance Company Limited"


def parse_bajaj_nl2(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
):
    logger.info(f"Parsing Bajaj NL2: {pdf_path}")
    return parse_header_driven_nl2(
        pdf_path=pdf_path,
        company_key=company_key,
        company_name_fallback=_FALLBACK_NAME,
        quarter=quarter,
        year=year,
    )
