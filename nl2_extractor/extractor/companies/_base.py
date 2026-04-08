"""
Shared extraction utilities for NL-5 Claims Schedule parsers.

Provides:
  - get_nl5_pages()      — filter PDF pages to FORM NL-5
  - detect_lob_columns() — scan header rows for LOB columns
  - detect_row_metrics()  — scan label column(s) for metric rows
  - extract_grid()        — positional grid extraction into PeriodData
  - run_sign_heuristics() — auto-detect and correct RI Ceded sign flips
  - parse_header_driven() — generic header-driven, page-count-agnostic parser
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.company_registry import COMPANY_DISPLAY_NAMES
from extractor.models import PeriodData
from extractor.normaliser import clean_number

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sign-heuristic constants
# ---------------------------------------------------------------------------
HEURISTIC_THRESHOLD_PCT = 0.001   # proportional tolerance on |CPD|
IDENTITY_TOLERANCE_ABS  = 2.0    # absolute floor (lakhs)
_NEAR_ZERO_THRESHOLD    = 1.0    # below this, sign is indeterminate

# ---------------------------------------------------------------------------
# Row metric detection — ordered list (specific before broad)
# ---------------------------------------------------------------------------
LABEL_TO_METRIC = [
    # Claims Paid
    ("claims paid (direct)",          "claims_paid_direct"),
    ("claims paid direct",            "claims_paid_direct"),
    ("clamis paid (direct)",          "claims_paid_direct"),  # OCR typo
    ("direct claims",                 "claims_paid_direct"),
    # RI Accepted
    ("re-insurance accepted",         "ri_accepted"),
    ("reinsurance accepted",          "ri_accepted"),
    ("re insurance accepted",         "ri_accepted"),
    # RI Ceded
    ("re-insurance ceded",            "ri_ceded"),
    ("reinsurance ceded",             "ri_ceded"),
    ("re insurance ceded",            "ri_ceded"),
    # Net Claim Paid
    ("net claims paid",               "net_claim_paid"),
    ("net claim paid",                "net_claim_paid"),
    # Outstanding
    ("outstanding at the end",        "outstanding_end"),
    ("claims outstanding at the end", "outstanding_end"),
    ("outstanding at the beginning",  "outstanding_begin"),
    ("claims outstanding at the beginning", "outstanding_begin"),
    # Net Incurred Claims
    ("net incurred claims",           "net_incurred_claims"),
    ("total claims incurred",         "net_incurred_claims"),
    ("total claim incurred",          "net_incurred_claims"),
    ("net claim incurred",            "net_incurred_claims"),
    ("net incurred",                  "net_incurred_claims"),
    # IBNR
    ("ibnr and ibner at the end",     "ibnr_end"),
    ("ibner at the end",              "ibnr_end"),
    ("ibnr at the end",               "ibnr_end"),
    ("ibnr and ibner at the beginning", "ibnr_begin"),
    ("ibner at the beginning",        "ibnr_begin"),
    ("ibnr at the beginning",         "ibnr_begin"),
    # Sub-breakdowns (lower priority)
    ("outside india",                 "claims_paid_outside_india"),
    ("in india",                      "claims_paid_in_india"),
    # Forex
    ("exchange fluctuation",          "fx_fluctuation"),
    ("foreign exchange",              "fx_fluctuation"),
    ("fx fluctuation",                "fx_fluctuation"),
]


# ---------------------------------------------------------------------------
# Backward-compatible TARGET_ROWS dict (used by parsers with manual row loops)
# New parsers should use detect_row_metrics() instead.
# ---------------------------------------------------------------------------
TARGET_ROWS = {
    "claims_paid_direct":   ["claims paid (direct)", "claims paid direct", "clamis paid (direct)", "direct claims"],
    "ri_accepted":          ["re-insurance accepted", "reinsurance accepted", "re insurance accepted"],
    "ri_ceded":             ["re-insurance ceded", "reinsurance ceded", "re insurance ceded"],
    "net_claim_paid":       ["net claims paid", "net claim paid"],
    "outstanding_end":      ["outstanding at the end", "claims outstanding at the end"],
    "outstanding_begin":    ["outstanding at the beginning", "claims outstanding at the beginning"],
    "net_incurred_claims":  ["net incurred claims", "total claims incurred", "total claim incurred",
                             "net claim incurred", "net incurred"],
    "ibnr_end":             ["ibnr and ibner at the end", "ibner at the end", "ibnr at the end"],
    "ibnr_begin":           ["ibnr and ibner at the beginning", "ibner at the beginning", "ibnr at the beginning"],
}

# ---------------------------------------------------------------------------
# NL-5 page detection
# ---------------------------------------------------------------------------
_NL5_RE = re.compile(r"(FORM\s+NL[-\s]?5|ne\s*t\s*-\s*i\s*c\s*5)", re.IGNORECASE)
_SMALL_PDF_PAGE_THRESHOLD = 12


def get_nl5_pages(pdf) -> list:
    """Return only the pages that belong to FORM NL-5."""
    all_pages = list(pdf.pages)
    if len(all_pages) <= _SMALL_PDF_PAGE_THRESHOLD:
        return all_pages

    nl5_pages = []
    for page in all_pages:
        text = page.extract_text() or ""
        if _NL5_RE.search(text):
            nl5_pages.append(page)

    if nl5_pages:
        return nl5_pages

    logger.warning("No FORM NL-5 header found; processing all pages")
    return all_pages


def resolve_company_name(company_key: str, pdf_path: str, fallback: str = "") -> str:
    """Resolve company display name with PDF-filename fallback."""
    name = COMPANY_DISPLAY_NAMES.get(company_key)
    if name:
        return name
    stem = Path(pdf_path).stem
    stem = re.sub(r'[_-](?:NL5|Q[1-4]|\d{6}|\d{4})$', '', stem, flags=re.IGNORECASE)
    words = re.sub(r'([a-z])([A-Z])', r'\1 \2', stem).replace('_', ' ').replace('-', ' ').split()
    if words:
        return ' '.join(words)
    return fallback or company_key.replace('_', ' ').title()


# ---------------------------------------------------------------------------
# Grid extraction
# ---------------------------------------------------------------------------
def extract_grid(
    table: list,
    row_metrics: Dict[int, str],
    lob_map: List[Tuple[str, int, int]],
    period_data: PeriodData,
):
    """Extract data from a positional grid table into period_data."""
    for row_idx, metric in row_metrics.items():
        if row_idx >= len(table):
            continue
        row = table[row_idx]
        for lob, qc, yc in lob_map:
            qv = clean_number(row[qc]) if qc is not None and qc < len(row) else None
            yv = clean_number(row[yc]) if yc is not None and yc < len(row) else None

            if qv is None and yv is None:
                continue

            if lob not in period_data.data:
                period_data.data[lob] = {}
            if metric not in period_data.data[lob]:
                period_data.data[lob][metric] = {"qtr": None, "ytd": None}

            if qv is not None and period_data.data[lob][metric]["qtr"] is None:
                period_data.data[lob][metric]["qtr"] = qv
            if yv is not None and period_data.data[lob][metric]["ytd"] is None:
                period_data.data[lob][metric]["ytd"] = yv


# ---------------------------------------------------------------------------
# Header-driven LOB detection (layout-agnostic)
# ---------------------------------------------------------------------------
HEADER_TO_LOB = [
    ("grand total",         "grand_total"),
    ("total miscellaneous", "total_miscellaneous"),
    ("total marine",        "total_marine"),
    ("total motor",         "total_motor"),
    ("motor total",         "total_motor"),
    ("motor-total",         "total_motor"),
    ("total health",        "total_health"),
    ("marine cargo",        "marine_cargo"),
    ("marine hull",         "marine_hull"),
    ("motor od",            "motor_od"),
    ("motor tp",            "motor_tp"),
    ("personal accident",   "personal_accident"),
    ("travel insurance",    "travel_insurance"),
    ("crop insurance",      "crop_insurance"),
    ("weather and crop",    "crop_insurance"),
    ("weather/crop",        "crop_insurance"),
    ("credit insurance",    "credit_insurance"),
    ("trade credit",        "credit_insurance"),
    ("credit",              "credit_insurance"),
    ("other miscellaneous", "other_miscellaneous"),
    ("other segment",       "other_segments"),
    ("others",              "other_miscellaneous"),
    ("workmen",             "wc_el"),
    ("employer",            "wc_el"),
    ("other liability",     "other_liability"),
    ("public",              "public_product_liability"),
    ("liability",           "public_product_liability"),
    ("specialty",           "specialty"),
    ("home",                "home"),
    ("marine",              "marine_cargo"),
    ("fire",                "fire"),
    ("health",              "health"),
    ("engineering",         "engineering"),
    ("aviation",            "aviation"),
]


def match_header(cell_text: str):
    """Return LOB key for a header cell, or None."""
    text = cell_text.replace("\n", " ").strip().lower()
    for pattern, lob_key in HEADER_TO_LOB:
        if pattern in text:
            return lob_key
    return None


def detect_lob_columns(table) -> List[Tuple[str, int, int]]:
    """Scan header rows and return list of (lob_key, qtr_col, ytd_col)."""
    if len(table) < 2:
        return []

    for header_row_idx in range(min(4, len(table) - 1)):
        if header_row_idx >= len(table):
            continue
        row0 = table[header_row_idx]
        if not any(match_header(c) for c in row0[1:] if c and c.strip()):
            continue

        period_row = table[header_row_idx + 1] if header_row_idx + 1 < len(table) else [None] * len(row0)
        lob_cols = []
        col = 1

        while col < len(row0):
            cell = row0[col]
            if not cell or not cell.strip():
                col += 1
                continue

            lob_key = match_header(cell)
            if lob_key is None:
                col += 1
                continue

            next_col = col + 1
            if next_col < len(row0) and not (row0[next_col] or "").strip():
                lob_cols.append((lob_key, col, next_col))
                col = next_col + 1
            else:
                period_text = (period_row[col] or "").lower()
                if "up to" in period_text or "upto" in period_text:
                    lob_cols.append((lob_key, None, col))
                else:
                    lob_cols.append((lob_key, col, None))
                col += 1

        if lob_cols:
            return lob_cols

    return []


# ---------------------------------------------------------------------------
# Row metric detection — replaces fragile hardcoded row indices
# ---------------------------------------------------------------------------
def detect_row_metrics(table) -> Dict[int, str]:
    """Auto-detect which row indices map to which NL-5 claims metrics.

    Scans col 0 first; falls back to col 1 (companies with S.No in col 0).
    Uses ordered LABEL_TO_METRIC for priority control.
    """
    metrics: Dict[int, str] = {}
    for ri, row in enumerate(table):
        if not row:
            continue
        label_0 = (row[0] or "").replace("\n", " ").strip().lower() if row[0] else ""
        label_1 = (row[1] or "").replace("\n", " ").strip().lower() \
            if len(row) > 1 and row[1] else ""
        label = label_0 or label_1   # col 1 fallback for S.No companies

        if not label:
            continue

        for pattern, metric_key in LABEL_TO_METRIC:
            if pattern in label and metric_key not in metrics.values():
                metrics[ri] = metric_key
                break
    return metrics


# ---------------------------------------------------------------------------
# Sign heuristic — ported from NL4, adapted for NL5 Claims identity
# ---------------------------------------------------------------------------
def _get_anchor_values(
    gt: dict, timewise: str
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Extract (ncp, cpd, acc, ced) from the anchor LOB for one timewise slot."""
    def _get(metric):
        return gt.get(metric, {}).get(timewise)
    return (_get("net_claim_paid"), _get("claims_paid_direct"),
            _get("ri_accepted"),   _get("ri_ceded"))


def _negate_ri_ceded(period_data: PeriodData) -> None:
    """Flip the sign of every RI Ceded value in the period (all LOBs, qtr+ytd)."""
    for lob in period_data.data:
        if "ri_ceded" in period_data.data[lob]:
            for slot in ("qtr", "ytd"):
                val = period_data.data[lob]["ri_ceded"].get(slot)
                if val is not None:
                    period_data.data[lob]["ri_ceded"][slot] = -val


def _run_sign_heuristic(
    period_data: PeriodData, company_key: str, period_label: str
) -> Optional[bool]:
    """Detect and auto-correct RI Ceded sign-convention flips for one period.

    Returns
    -------
    True   — flip detected AND applied (period_data mutated).
    False  — standard convention confirmed OR strategic recovery; no mutation.
    None   — could not determine; no mutation.

    Identity: NCP = CPD + RI_Acc + RI_Ced   (expects RI_Ced < 0)
    Anchor:   grand_total → total_health fallback.
    Timewise: YTD first, then QTR fallback.
    Tolerance: max(IDENTITY_TOLERANCE_ABS, |CPD| × HEURISTIC_THRESHOLD_PCT).
    """
    # 1. Find anchor LOB
    gt = period_data.data.get("grand_total") or period_data.data.get("total_health")
    if not gt:
        logger.debug(
            f"[HEURISTIC] {company_key} {period_label}: "
            f"no grand_total or total_health anchor — skipping."
        )
        return None

    # 2. Try YTD; fall back to QTR
    ncp, cpd, acc, ced = _get_anchor_values(gt, "ytd")
    timewise = "ytd"
    if any(v is None for v in (ncp, cpd, ced)):
        ncp, cpd, acc, ced = _get_anchor_values(gt, "qtr")
        timewise = "qtr"

    if any(v is None for v in (ncp, cpd, ced)):
        logger.debug(
            f"[HEURISTIC] {company_key} {period_label}: "
            f"NCP/CPD/RIC unavailable in both YTD and QTR — skipping."
        )
        return None

    # 3. Handle absent RI Accepted (health-only / zero-RI companies)
    acc_eff = acc if acc is not None else 0.0

    # 4. Scale-aware tolerance
    tolerance = max(IDENTITY_TOLERANCE_ABS, abs(cpd) * HEURISTIC_THRESHOLD_PCT)

    # 5. Identity deltas
    std_delta  = abs(ncp - (cpd + acc_eff + ced))   # expects RIC < 0
    flip_delta = abs(ncp - (cpd + acc_eff - ced))   # expects RIC > 0

    # 6. Near-zero: sign is indeterminate
    if abs(ced) < _NEAR_ZERO_THRESHOLD:
        return None

    # 7. Decision tree
    if ced <= -_NEAR_ZERO_THRESHOLD:
        # Looks standard (negative)
        if std_delta <= tolerance:
            return False
        else:
            logger.warning(
                f"[HEURISTIC] {company_key} {period_label}: RIC negative ({ced:.2f}) "
                f"but NCP identity fails (std_delta={std_delta:.2f}, tol={tolerance:.2f})."
            )
            return None
    else:
        # Looks flipped (positive)
        if flip_delta <= tolerance:
            logger.info(
                f"[HEURISTIC] Sign flip triggered for {company_key} {period_label} (Claims)."
            )
            period_data.auto_negated_ri = True
            _negate_ri_ceded(period_data)
            return True
        elif std_delta <= tolerance:
            logger.info(
                f"[HEURISTIC] Strategic recovery confirmed for {company_key} {period_label}: "
                f"RIC positive ({ced:.2f}) and standard identity holds."
            )
            return False
        else:
            logger.warning(
                f"[HEURISTIC] {company_key} {period_label}: RIC positive ({ced:.2f}) "
                f"but neither identity matches (std={std_delta:.2f}, "
                f"flip={flip_delta:.2f}, tol={tolerance:.2f})."
            )
            return None


def run_sign_heuristics(
    cy_data: Optional[PeriodData], py_data: Optional[PeriodData], company_key: str
) -> Tuple[Optional[bool], Optional[bool]]:
    """Run sign heuristic for both periods; check cross-period consistency.

    This is the **public entry point** all parsers should call.
    """
    cy_result = _run_sign_heuristic(cy_data, company_key, "current") \
        if cy_data is not None else None
    py_result = _run_sign_heuristic(py_data, company_key, "prior") \
        if py_data is not None else None

    if cy_result is not None and py_result is not None and cy_result != py_result:
        logger.warning(
            f"[HEURISTIC] Cross-period inconsistency for {company_key}: "
            f"CY flipped={cy_result}, PY flipped={py_result}."
        )

    return cy_result, py_result


# ---------------------------------------------------------------------------
# Fiscal year detection — for CY/PY assignment in parse_header_driven
# ---------------------------------------------------------------------------
_FISCAL_YEAR_RE = re.compile(r'\b(20\d\d)[/-](\d{2})\b')


def detect_period_year(table) -> Optional[int]:
    """Scan first 5 rows for fiscal year label; return start year or None."""
    for row in table[:5]:
        for cell in row:
            if not cell:
                continue
            m = _FISCAL_YEAR_RE.search(str(cell))
            if m:
                return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Generic header-driven parser
# ---------------------------------------------------------------------------
def parse_header_driven(
    pdf_path: str,
    company_key: str,
    company_name_fallback: str,
    quarter: str = "",
    year: str = "",
) -> "CompanyExtract":
    """Shared header-driven, page-count-agnostic NL-5 parser.

    CY/PY assignment: uses year-hint-based detection (like NL4).
    Tables with the higher fiscal year = CY; lower = PY.
    Falls back to table-position if no year labels found.
    """
    import pdfplumber
    from extractor.models import CompanyExtract as _CE, PeriodData as _PD

    company_name = resolve_company_name(company_key, pdf_path, company_name_fallback)

    extract = _CE(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=company_name,
        form_type="NL5",
        quarter=quarter,
        year=year,
    )
    cy = _PD(period_label="current")
    py = _PD(period_label="prior")

    candidates = []   # (year_hint, position_idx, table, lob_cols, row_metrics)

    with pdfplumber.open(pdf_path) as pdf:
        position_idx = 0

        for page in get_nl5_pages(pdf):
            # Track the richest LOB detection seen so far on this page.
            # This prevents a stray single-cell LOB header later in the page
            # from overwriting a correct full-LOB map found earlier.
            # We reset per page so that multi-page PDFs (e.g. Liberty, one
            # LOB-segment per page) are not affected by a richer previous page.
            page_best_lob_cols = []
            for table_obj in page.find_tables():
                table = table_obj.extract()
                if not table or len(table) < 3:
                    continue

                lob_cols = detect_lob_columns(table)
                if len(lob_cols) > len(page_best_lob_cols):
                    page_best_lob_cols = lob_cols
                effective_lob_cols = lob_cols if len(lob_cols) >= len(page_best_lob_cols) \
                    else page_best_lob_cols
                if not effective_lob_cols:
                    continue

                row_metrics = detect_row_metrics(table)
                if not row_metrics:
                    continue

                year_hint = detect_period_year(table)
                candidates.append((
                    year_hint, position_idx, table,
                    effective_lob_cols, row_metrics,
                ))
                position_idx += 1

    # --- CY/PY assignment ---
    year_hints = [c[0] for c in candidates if c[0] is not None]
    if year_hints:
        max_year = max(year_hints)
        for year_hint, pos, table, lob_cols, rm in candidates:
            period_data = cy if (year_hint is not None and year_hint >= max_year) else py
            extract_grid(table, rm, lob_cols, period_data)
    else:
        # Fallback: even-indexed tables = CY, odd = PY
        for year_hint, pos, table, lob_cols, rm in candidates:
            period_data = cy if pos % 2 == 0 else py
            extract_grid(table, rm, lob_cols, period_data)

    run_sign_heuristics(cy, py, company_key)

    extract.current_year = cy
    extract.prior_year = py
    return extract
