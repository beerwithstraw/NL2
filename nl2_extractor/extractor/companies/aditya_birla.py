import logging
from typing import Dict, Any, List
from pathlib import Path

from extractor.collector import collect_tables
from extractor.normaliser import clean_number
from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base import resolve_company_name, run_sign_heuristics

logger = logging.getLogger(__name__)

# Column mapping (LOB -> {qtr: col_idx, ytd: col_idx})
# col 0 = empty, col 1 = label, cols 2-5 = qtr data, cols 6-9 = ytd data
ADITYA_COL_MAP = {
    "health":            {"qtr": 2, "ytd": 6},
    "personal_accident": {"qtr": 3, "ytd": 7},
    "travel_insurance":  {"qtr": 4, "ytd": 8},
    "total_health":      {"qtr": 5, "ytd": 9},
}

# Row mapping (Metric -> row_idx in collect_tables output)
# Aditya Birla places OS_end (Add) BEFORE OS_begin (Less) — unusual but confirmed.
ADITYA_CY_ROWS = {
    "claims_paid_direct":  5,
    "ri_accepted":         6,
    "ri_ceded":            7,
    "net_claim_paid":      8,
    "outstanding_end":     9,   # "Add: Claims Outstanding at end" (before begin)
    "outstanding_begin":   10,  # "Less: Claims Outstanding at beginning"
    "net_incurred_claims": 11,
    "ibnr_end":            15,
    "ibnr_begin":          16,
}

ADITYA_PY_ROWS = {
    "claims_paid_direct":  20,
    "ri_accepted":         21,
    "ri_ceded":            22,
    "net_claim_paid":      23,
    "outstanding_end":     24,
    "outstanding_begin":   25,
    "net_incurred_claims": 26,
    "ibnr_end":            30,
    "ibnr_begin":          31,
}

def _extract_aditya_period(rows: List[List[Any]], row_map: Dict[str, int]) -> PeriodData:
    period_data = PeriodData(period_label="")
    
    for lob, cols in ADITYA_COL_MAP.items():
        if lob not in period_data.data:
            period_data.data[lob] = {}
            
        for metric, row_idx in row_map.items():
            if row_idx >= len(rows):
                continue
            
            row = rows[row_idx]
            qtr_val = clean_number(row[cols["qtr"]]) if cols["qtr"] < len(row) else None
            ytd_val = clean_number(row[cols["ytd"]]) if cols["ytd"] < len(row) else None
            
            # Negate RI Ceded for consistency (Deprecated in Phase 2)
            if metric == "ri_ceded":
                pass
            
            if qtr_val is not None or ytd_val is not None:
                period_data.data[lob][metric] = {"qtr": qtr_val, "ytd": ytd_val}
                
    return period_data

def parse_aditya_birla(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing Aditya Birla Health PDF: {pdf_path}")
    
    tables = collect_tables(pdf_path, extraction_strategy="lines")
    
    extract = CompanyExtract(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=resolve_company_name(company_key, pdf_path, "Aditya Birla Health Insurance Co. Limited"),
        form_type="NL5",
        quarter=quarter,
        year=year,
    )
    
    if not tables:
        logger.error("No tables found in Aditya Birla PDF.")
        return extract
        
    t = tables[0]
    rows = t["rows"]
    
    # CY: Rows 4-13
    extract.current_year = _extract_aditya_period(rows, ADITYA_CY_ROWS)
    extract.current_year.period_label = "current"
    
    # PY: Rows 17-26
    if len(rows) > 17:
        extract.prior_year = _extract_aditya_period(rows, ADITYA_PY_ROWS)
        extract.prior_year.period_label = "prior"
    
    run_sign_heuristics(extract.current_year, extract.prior_year, company_key)
        
    return extract
