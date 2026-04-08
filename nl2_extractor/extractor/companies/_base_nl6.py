"""
Shared extraction utilities for NL-6 Commission Schedule parsers.

Provides:
  - get_nl6_pages()      — filter PDF pages to FORM NL-6
  - detect_lob_columns() — scan header rows for LOB columns
  - detect_row_metrics() — section-aware scan for NL-6 commission row metrics
  - extract_grid()        — positional grid extraction into PeriodData
  - parse_header_driven() — generic header-driven, page-count-agnostic parser

Key NL-6 differences from NL-5:
  - No sign heuristics (RI Ceded sign flip logic does not apply to commissions).
  - detect_row_metrics() is section-aware: rows before the
    "Break-up of the expenses" separator belong to the top section;
    rows after belong to the channel breakdown section.
  - "MISP (Direct)" maps to distribution_fees in the top section,
    but to misp_direct in the channel section.
  - "In India" and "Outside India" footer rows are always skipped.
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
# NL-6 page detection
# ---------------------------------------------------------------------------
_NL6_RE = re.compile(r"FORM\s+NL[-\s]?0?6\b", re.IGNORECASE)
_SMALL_PDF_PAGE_THRESHOLD = 6


def get_nl6_pages(pdf) -> list:
    """Return only the pages that belong to FORM NL-6."""
    all_pages = list(pdf.pages)
    if len(all_pages) <= _SMALL_PDF_PAGE_THRESHOLD:
        return all_pages

    nl6_pages = []
    for page in all_pages:
        text = page.extract_text() or ""
        if _NL6_RE.search(text):
            nl6_pages.append(page)

    if nl6_pages:
        return nl6_pages

    logger.warning("No FORM NL-6 header found; processing all pages")
    return all_pages


def resolve_company_name(company_key: str, pdf_path: str, fallback: str = "") -> str:
    """Resolve company display name with PDF-filename fallback."""
    name = COMPANY_DISPLAY_NAMES.get(company_key)
    if name:
        return name
    stem = Path(pdf_path).stem
    stem = re.sub(r'[_-](?:NL6|Q[1-4]|\d{6}|\d{4})$', '', stem, flags=re.IGNORECASE)
    words = re.sub(r'([a-z])([A-Z])', r'\1 \2', stem).replace('_', ' ').replace('-', ' ').split()
    if words:
        return ' '.join(words)
    return fallback or company_key.replace('_', ' ').title()


# ---------------------------------------------------------------------------
# Row metric detection — two ordered lists, one per section
# (specific-before-broad to prevent false matches)
# ---------------------------------------------------------------------------

# Top section: rows BEFORE the "Break-up of the expenses" separator
_TOP_LABEL_TO_METRIC: List[Tuple[str, str]] = [
    # Gross and net must come before the bare "commission" fallback
    ("gross commission",                    "gross_commission"),
    ("total commission",                    "gross_commission"),
    ("direct commission",                   "gross_commission"),   # ManipalCigna variant
    ("net commission",                      "net_commission"),
    # Commission & Remuneration
    ("commission & remuneration",           "commission_remuneration"),
    ("commission and remuneration",         "commission_remuneration"),
    ("commission remuneration",             "commission_remuneration"),
    # Rewards
    ("rewards",                             "rewards"),
    # Distribution fees (including Bajaj pages 3/4 variant)
    ("distribution fees",                   "distribution_fees"),
    ("misp (direct)",                       "distribution_fees"),
    # RI Accepted — commission-specific labels first, then generic
    ("commission on re-insurance accepted", "ri_accepted_commission"),
    ("commission on reinsurance accepted",  "ri_accepted_commission"),
    ("re-insurance accepted",               "ri_accepted_commission"),
    ("reinsurance accepted",                "ri_accepted_commission"),
    ("re insurance accepted",               "ri_accepted_commission"),
    ("re- insurance accepted",              "ri_accepted_commission"),  # HDFC ERGO: "Re- insurance Accepted"
    # RI Ceded — commission-specific labels first, then generic
    ("commission on re-insurance ceded",    "ri_ceded_commission"),
    ("commission on reinsurance ceded",     "ri_ceded_commission"),
    ("re-insurance ceded",                  "ri_ceded_commission"),
    ("reinsurance ceded",                   "ri_ceded_commission"),
    ("re insurance ceded",                  "ri_ceded_commission"),
    ("re- insurance ceded",                 "ri_ceded_commission"),     # HDFC ERGO: "Re- insurance Ceded"
]

# Channel section: rows AFTER the "Break-up of the expenses" separator
_CHANNEL_LABEL_TO_METRIC: List[Tuple[str, str]] = [
    # Multi-word entries first (before their single-word substrings)
    ("corporate agent (bank)",              "corporate_agent_bank"),
    ("corporate agents (bank)",             "corporate_agent_bank"),
    ("corporate agents (banks",              "corporate_agent_bank"),   # IFFCO: "Corporate Agents (Banks / FII / HFC)"
    ("corporate agents-bank",               "corporate_agent_bank"),   # Care Health: "Corporate Agents-Banks/FII/HFC"
    ("corporate agent (other)",             "corporate_agent_other"),
    ("corporate agents (other)",            "corporate_agent_other"),
    ("corporate agents (others)",           "corporate_agent_other"),
    ("corporate agent (others)",            "corporate_agent_other"),
    ("corporate agents-other",              "corporate_agent_other"),  # Care Health: "Corporate Agents-Others"
    ("corporate agents -other",             "corporate_agent_other"),  # ManipalCigna: space before hyphen
    ("corporate agency",                    "corporate_agent_other"),  # ECGC: generic corporate agency
    ("motor insurance service provider (direct)",     "misp_direct"),
    ("motor insurance service provider (dealership)", "misp_dealership"),
    ("misp (direct)",                       "misp_direct"),
    ("misp broker",                         "misp_direct"),        # Universal Sompo: "MISP Broker"
    ("misp (dealership)",                   "misp_dealership"),
    ("web aggregator",                      "web_aggregator"),
    ("insurance marketing firm",            "insurance_marketing_firm"),
    ("insuranc marketing",                  "insurance_marketing_firm"),  # IndusInd CY: "Insuranc Marketing Firm" (OCR drop)
    ("common service centre",               "common_service_centre"),
    ("common service center",               "common_service_centre"),  # US spelling variant
    ("point of sales",                      "point_of_sales"),
    ("direct business",                     "direct_selling"),         # Care Health: "Direct Business - Online"
    ("direct selling",                      "direct_selling"),
    # micro_agent must precede bare "agent" to avoid greedy substring match
    ("micro agent",                         "micro_agent"),
    # Single-word entries (after all multi-word to avoid greedy match)
    ("broker",                              "broker"),
    ("agent",                               "agent"),
    ("other channel",                       "other_channels"),
    ("others",                              "other_channels"),
    ("referral arrangements",               "referral_arrangements"),
    # bare "other" must come after all multi-word entries containing "other"
    ("other",                               "other_channels"),
    ("total",                               "total_channel"),
]

# Rows to always skip regardless of section
_SKIP_LABELS = {"in india", "outside india"}

# Section boundary triggers — any matching label marks start of channel section
_SECTION_BOUNDARIES = (
    "break-up of the expenses",
    "channel wise break-up",    # SBI General variant
)


def detect_row_metrics(table, start_in_channel_section: bool = False) -> Dict[int, str]:
    """Auto-detect which row indices map to which NL-6 commission metrics.

    Scans col 0 first; falls back to col 1 (companies with S.No in col 0).
    Section-aware: uses top-section mappings before the "Break-up of the
    expenses" separator row, and channel-section mappings after it.

    start_in_channel_section: set True when the table contains only channel
    breakdown rows (no section boundary present), e.g. Care Health T1.
    """
    metrics: Dict[int, str] = {}
    in_channel_section = start_in_channel_section

    for ri, row in enumerate(table):
        if not row:
            continue
        label_0 = (row[0] or "").replace("\n", " ").strip().lower() if row[0] else ""
        label_1 = (row[1] or "").replace("\n", " ").strip().lower() \
            if len(row) > 1 and row[1] else ""
        label = label_0 or label_1

        if not label:
            continue

        # Always skip footer rows and sub-rows (e.g. "- officers/employees")
        if label in _SKIP_LABELS or label.startswith("-"):
            continue

        # Section boundary detection — do not assign a metric to this row
        if any(b in label for b in _SECTION_BOUNDARIES):
            in_channel_section = True
            continue

        pairs = _CHANNEL_LABEL_TO_METRIC if in_channel_section else _TOP_LABEL_TO_METRIC
        for pattern, metric_key in pairs:
            if pattern in label and metric_key not in metrics.values():
                metrics[ri] = metric_key
                break

    return metrics


# ---------------------------------------------------------------------------
# 2-row LOB header merging
# ---------------------------------------------------------------------------
_CALENDAR_YEAR_RE = re.compile(r'\b(20\d\d)\b')


def detect_calendar_year(table) -> Optional[int]:
    """Scan first 5 rows for a bare calendar year (e.g. 'Dec 2025').
    Returns the year int or None. Used when fiscal YYYY-YY labels are absent."""
    for row in table[:5]:
        for cell in row:
            if not cell:
                continue
            m = _CALENDAR_YEAR_RE.search(str(cell))
            if m:
                return int(m.group(1))
    return None


def merge_lob_header_rows(table) -> List[Tuple[str, int, int]]:
    """Build LOB columns from a 2-row spanning header.

    Row 0 contains category spans (e.g. 'Miscellaneous') and row 1 has the
    actual sub-LOB names ('Motor OD', 'Motor TP', ...).

    Merge rule:
      - Both rows non-empty at the same column → row 0 is a span → use row 1.
      - Only one row has a value → use that value.
    Returns detect_lob_columns() result on the merged header.
    """
    if len(table) < 3:
        return []

    row0 = list(table[0])
    row1 = list(table[1])
    r1 = row1 + [""] * max(0, len(row0) - len(row1))

    merged = [
        r1[i] if (cell and cell.strip() and r1[i] and r1[i].strip())
        else (cell if (cell and cell.strip()) else r1[i])
        for i, cell in enumerate(row0)
    ]

    # Build synthetic table: [merged_header, period_row, data_rows...]
    synthetic = [merged, table[2]] + list(table[2:])
    return detect_lob_columns(synthetic)


# ---------------------------------------------------------------------------
# Grid extraction (identical logic to NL-5 _base.py)
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
# Header-driven LOB detection (identical to NL-5 _base.py — LOBs unchanged)
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
    ("motor (od)",          "motor_od"),         # SBI General: "Motor (OD)"
    ("motor tp",            "motor_tp"),
    ("motor (tp)",          "motor_tp"),         # SBI General: "Motor (TP)"
    ("motor total",         "total_motor"),      # SBI General: "Motor Total"
    ("personal accident",   "personal_accident"),
    ("travel insurance",    "travel_insurance"),
    ("travel",              "travel_insurance"),    # Go Digit: bare "Travel" sub-header
    ("crop insurance",      "crop_insurance"),
    ("weather and crop",    "crop_insurance"),
    ("weather/crop",        "crop_insurance"),
    ("crop / weather",      "crop_insurance"),   # ICICI Lombard: "Crop / Weather Insurance"
    ("weather & crop",      "crop_insurance"),   # SBI General: "Weather & Crop Insurance"
    ("crop",                "crop_insurance"),   # Magma: bare "Crop"
    ("credit insurance",    "credit_insurance"),
    ("trade credit",        "credit_insurance"),
    ("credit",              "credit_insurance"),
    ("other miscellaneous", "other_miscellaneous"),
    ("other segment",       "other_segments"),
    ("others",              "other_miscellaneous"),
    ("miscellaneous",       "other_miscellaneous"),  # Go Digit: bare "Miscellaneous" sub-header
    ("workmen",             "wc_el"),
    ("employer",            "wc_el"),
    ("other liability",     "other_liability"),
    ("public",              "public_product_liability"),
    ("liability",           "public_product_liability"),
    ("specialty",           "specialty"),
    ("speciality",          "specialty"),        # HDFC ERGO: "Speciality"
    ("home",                "home"),
    ("marine",              "marine_cargo"),
    ("fire",                "fire"),
    ("health",              "health"),
    ("engineering",         "engineering"),
    ("aviation",            "aviation"),
    # bare "Total" — must be last; only matches when no specific "total X" pattern did
    ("total",               "grand_total"),      # SBI General: bare "Total" column = Grand Total
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
# Generic header-driven parser (NL-6 version — no sign heuristics)
# ---------------------------------------------------------------------------
def parse_header_driven(
    pdf_path: str,
    company_key: str,
    company_name_fallback: str,
    quarter: str = "",
    year: str = "",
) -> "CompanyExtract":
    """Shared header-driven, page-count-agnostic NL-6 Commission Schedule parser.

    CY/PY assignment: uses year-hint-based detection.
    Tables with the higher fiscal year = CY; lower = PY.
    Falls back to table-position if no year labels found.

    No sign heuristics are applied — RI Ceded sign conventions do not
    apply to commission schedules.
    """
    import pdfplumber
    from extractor.models import CompanyExtract as _CE, PeriodData as _PD

    company_name = resolve_company_name(company_key, pdf_path, company_name_fallback)

    extract = _CE(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=company_name,
        form_type="NL6",
        quarter=quarter,
        year=year,
    )
    cy = _PD(period_label="current")
    py = _PD(period_label="prior")

    candidates = []   # (year_hint, position_idx, table, lob_cols, row_metrics)

    with pdfplumber.open(pdf_path) as pdf:
        position_idx = 0

        for page in get_nl6_pages(pdf):
            # Track the richest LOB detection seen so far on this page.
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

    # No sign heuristics for NL-6 commission schedules

    extract.current_year = cy
    extract.prior_year = py
    return extract
