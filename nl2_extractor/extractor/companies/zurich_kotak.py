"""
Parser for Zurich Kotak General Insurance Company (India) Limited (NL-6 Commission Schedule).

PDF Structure: 2 NL-6 pages, 2 tables per page. T0=CY (2025), T1=PY (2024).
  Page 0: fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp,
          total_motor, health, personal_accident, travel_insurance, total_health (11 LOBs, 23c)
  Page 1: wc_el, public_product_liability, engineering, aviation, crop_insurance,
          other_miscellaneous, total_miscellaneous, grand_total (9 LOBs, 19c)

detect_lob_columns() resolves LOBs cleanly from r0.
detect_calendar_year() returns 2025 for T0 and 2024 for T1 on both pages.
detect_row_metrics() handles top-section and channel-section rows.
-> parse_header_driven handles this without customisation.
"""

import logging
from extractor.companies._base_nl6 import parse_header_driven

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Zurich Kotak General Insurance Company (India) Limited"


def parse_zurich_kotak(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> "CompanyExtract":
    logger.info(f"Parsing Zurich Kotak NL-6 PDF: {pdf_path}")
    return parse_header_driven(pdf_path, company_key, _FALLBACK_NAME, quarter, year)
