"""
Dedicated Parser for Narayana Health Insurance Limited.

PDF Structure: 1 page, 1 table merged (CY rows 0-15, PY rows 16-31).
Table: 33 rows x 9 cols.

LOB columns (0-indexed):
  health(1,2), total_health(3,4), total_miscellaneous(5,6), grand_total(7,8)

CY row structure (0-indexed within table):
  0-1: headers
  2: LOB names
  3: period headers
  4: claims_paid_direct
  5: ri_accepted
  6: ri_ceded
  7: net_claim_paid
  8: outstanding_begin
  9: outstanding_end
  10: net_incurred_claims

PY row structure (offset +16):
  16-17: headers
  18: LOB names
  19: period headers
  20: claims_paid_direct
  21: ri_accepted
  22: ri_ceded
  23: net_claim_paid
  24: outstanding_begin
  25: outstanding_end
  26: net_incurred_claims
"""

import logging
from pathlib import Path
from typing import List, Tuple
import pdfplumber
from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base import extract_grid, get_nl5_pages, run_sign_heuristics
from config.company_registry import COMPANY_DISPLAY_NAMES

logger = logging.getLogger(__name__)

LOB_MAP: List[Tuple[str, int, int]] = [
    ("health",              1, 2),
    ("total_health",        3, 4),
    ("total_miscellaneous", 5, 6),
    ("grand_total",         7, 8),
]

CY_METRICS = {4: "claims_paid_direct", 5: "ri_accepted", 6: "ri_ceded",
              7: "net_claim_paid", 8: "outstanding_begin", 9: "outstanding_end", 10: "net_incurred_claims"}
PY_METRICS = {20: "claims_paid_direct", 21: "ri_accepted", 22: "ri_ceded",
              23: "net_claim_paid", 24: "outstanding_begin", 25: "outstanding_end", 26: "net_incurred_claims"}


def parse_narayana_health(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing Narayana Health PDF: {pdf_path}")
    company_name = COMPANY_DISPLAY_NAMES.get(company_key, "Narayana Health Insurance Limited")
    extract = CompanyExtract(source_file=Path(pdf_path).name, company_key=company_key,
                             company_name=company_name, form_type="NL6", quarter=quarter, year=year)
    cy = PeriodData(period_label="current")
    py = PeriodData(period_label="prior")
    with pdfplumber.open(pdf_path) as pdf:
        nl4_pages = get_nl5_pages(pdf)
        if not nl4_pages:
            logger.warning("No NL-4 pages found"); return extract
        data_tables = [t for t in nl4_pages[0].extract_tables() if t and len(t) > 1]
        if data_tables:
            extract_grid(data_tables[0], CY_METRICS, LOB_MAP, cy, null_to_zero=True)
            extract_grid(data_tables[0], PY_METRICS, LOB_MAP, py, null_to_zero=True)

    run_sign_heuristics(cy, py, company_key)
    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
