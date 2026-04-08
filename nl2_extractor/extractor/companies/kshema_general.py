"""
Parser for Kshema General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 NL-6 page, 2 tables (41 cols each).
  T0 — CY data (period ended 31st December 2025)
  T1 — PY data (period ended 31st December 2024)

LOB header: single row (r0) with LOB names directly.
  20 LOBs: fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp,
  total_motor, health, personal_accident, travel_insurance, total_health,
  wc_el, public_product_liability, engineering, aviation, crop_insurance,
  other_segments, other_miscellaneous, total_miscellaneous, grand_total.

Column layout: 2 columns per LOB — (qtr, ytd).
  41 cols total: col 0 = row label, cols 1-40 = 20 LOBs × 2.

Section boundary: "Break-up of the expenses (Gross)..." is a row within the
  same table — detect_row_metrics() section-boundary logic applies.

CY/PY assignment: detect_period_year() returns None (period headers are
  garbled by OCR). Falls back to table-position: T0 (even) = CY, T1 (odd) = PY.
  This is the correct assignment confirmed against the PDF.

NOTE: The actual PDF has severe OCR garbling that interleaves characters from
  adjacent rows into single cells. detect_lob_columns() and detect_row_metrics()
  both fail on this PDF as-is. This parser describes the correct ideal-PDF
  structure; the OCR issue must be resolved separately.
"""

import logging

from extractor.companies._base_nl6 import parse_header_driven

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Kshema General Insurance Company Limited"


def parse_kshema_general(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
):
    logger.info(f"Parsing Kshema General NL-6 PDF: {pdf_path}")
    return parse_header_driven(
        pdf_path,
        company_key,
        _FALLBACK_NAME,
        quarter=quarter,
        year=year,
    )
