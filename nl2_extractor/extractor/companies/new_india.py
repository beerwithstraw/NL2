"""
Dedicated Parser for The New India Assurance Company Limited (NL-2).

Special Characteristics:
1.  Year-Aware Column Detection: Disambiguates Current (2025) vs Previous (2024)
    using date strings in headers to avoid the generic "Upto" column shift.
2.  Stacked P&L Reconciliation: Properly handles the 'Total A' row which, in
    New India's filing, only sums Investment and Other Income items.
"""

import logging
import re
from typing import Dict, Optional, List, Tuple
from pathlib import Path
import pdfplumber

from extractor.models import NL2Extract, NL2Data
from extractor.companies._base_nl2 import (
    get_nl2_pages,
    resolve_company_name,
    _expand_stacked_rows,
    detect_pl_rows,
    extract_nl2_grid,
    _QTR_KEYWORD_RE,
    _YTD_KEYWORD_RE,
    _derive_other_expenses,
    _derive_provision_taxation,
)

logger = logging.getLogger(__name__)

# Specialized year extractor for New India — matches any DD.MM.YYYY date
# (Q3 uses 31.12.YYYY, Q1 uses 30.06.YYYY, Q2 uses 30.09.YYYY)
_NI_YEAR_RE = re.compile(r'\d{2}\.\d{2}\.(20\d{2})')

def parse_new_india_nl2(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> NL2Extract:
    """Entry point for New India Assurance NL-2 extraction (Signature-Matched)."""
    
    extract = NL2Extract(
        company_name=resolve_company_name(company_key, pdf_path),
        company_key=company_key,
        quarter=quarter or "Q3",
        year=year or "20252026",
        source_file=Path(pdf_path).name,
    )
    extract.data = NL2Data(data={})

    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = get_nl2_pages(pdf)
            found = False
            for page in pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 10:
                        continue
                    
                    expanded = _expand_stacked_rows(table)
                    
                    # Step 1: Dedicated Year-Aware Column Detection
                    period_cols = _detect_period_columns_ni(expanded)
                    if not any(v is not None for v in period_cols.values()):
                        continue

                    # Step 2: Section-aware row detection
                    pl_rows = detect_pl_rows(expanded)
                    if not pl_rows:
                        continue

                    # Step 3: Populate the grid
                    extract_nl2_grid(expanded, pl_rows, period_cols, extract.data)
                    
                    logger.info(
                        f"New India Dedicated Parser: Extracted {len(pl_rows)} rows | "
                        f"period_cols={period_cols}"
                    )
                    found = True
                    break
                if found:
                    break
    except Exception as e:
        logger.error(f"New India Dedicated Parser failed: {e}")

    # Step 4: Specialized derivations
    _derive_other_income_ni(extract.data)
    _derive_other_expenses(extract.data)
    _derive_provision_taxation(extract.data)

    return extract


def _detect_period_columns_ni(table: list) -> Dict[str, Optional[int]]:
    """
    Robust date-aware column detection for New India.
    Definitively anchors 2025 as CY and 2024 as PY.
    """
    period_cols = {"cy_qtr": None, "cy_ytd": None, "py_qtr": None, "py_ytd": None}
    
    # DEBUG: Track detection
    found_info = []

    for ri, row in enumerate(table[:15]):
        for ci, cell in enumerate(row):
            if ci < 2 or not cell:
                continue
            
            text = str(cell).replace("\n", " ").strip()
            
            # Use specific NI_YEAR_RE to disambiguate
            m = _NI_YEAR_RE.search(text)
            if not m:
                continue
            
            year = int(m.group(1))
            upper_text = text.upper()
            is_qtr = "QUARTER" in upper_text
            is_ytd = "UPTO" in upper_text or "YEAR" in upper_text or "PERIOD" in upper_text
            
            if is_ytd:
                if year == 2025 and period_cols["cy_ytd"] is None:
                    period_cols["cy_ytd"] = ci
                    found_info.append(f"CY_YTD={ci} (found '{text}')")
                elif year == 2024 and period_cols["py_ytd"] is None:
                    period_cols["py_ytd"] = ci
                    found_info.append(f"PY_YTD={ci} (found '{text}')")
            elif is_qtr:
                if year == 2025 and period_cols["cy_qtr"] is None:
                    period_cols["cy_qtr"] = ci
                    found_info.append(f"CY_QTR={ci} (found '{text}')")
                elif year == 2024 and period_cols["py_qtr"] is None:
                    period_cols["py_qtr"] = ci
                    found_info.append(f"PY_QTR={ci} (found '{text}')")

    if found_info:
        print(f"DEBUG [New India]: {', '.join(found_info)}")
    
    return period_cols


def _derive_other_income_ni(nl2_data: NL2Data) -> None:
    """Derive Other Income for New India's P&L layout.

    Total A = Operating Profit (Fire + Marine + Misc)
             + Investment Income (Interest + Profit - Loss +/- Amort)
             + Other Income

    The previous formula omitted operating profit, producing a delta equal
    to op_sum in every TOTAL_A_DERIVATION check.
    """
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        total_a_pdf = nl2_data.data.get("total_a", {}).get(period)
        if total_a_pdf is None:
            continue

        op_fire   = nl2_data.data.get("op_fire",            {}).get(period) or 0
        op_marine = nl2_data.data.get("op_marine",          {}).get(period) or 0
        op_misc   = nl2_data.data.get("op_miscellaneous",   {}).get(period) or 0
        inv_int   = nl2_data.data.get("inv_interest_dividend_rent", {}).get(period) or 0
        inv_prof  = nl2_data.data.get("inv_profit_on_sale", {}).get(period) or 0
        inv_loss  = nl2_data.data.get("inv_loss_on_sale",   {}).get(period) or 0
        inv_amort = nl2_data.data.get("inv_amortization",   {}).get(period) or 0

        op_sum  = op_fire + op_marine + op_misc
        inv_sum = inv_int + inv_prof + inv_loss + inv_amort
        other_inc = total_a_pdf - op_sum - inv_sum

        nl2_data.data.setdefault("other_income", {})[period] = round(other_inc, 4)
