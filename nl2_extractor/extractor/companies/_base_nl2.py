"""
Shared extraction utilities for NL-2-B-PL Profit and Loss Account parsers.

Provides:
  - get_nl2_pages()            -- filter PDF pages to FORM NL-2
  - detect_period_columns()    -- scan header rows for the 4 period columns
  - detect_pl_rows()           -- section-aware P&L row detection (state machine)
  - extract_nl2_grid()         -- extract data into NL2Data
  - parse_header_driven_nl2()  -- generic header-driven parser for standard layouts

Key design:
  - Labels are in col 1 (col 0 has serial numbers in most NL-2 PDFs)
  - 4 period columns: cy_qtr, cy_ytd, py_qtr, py_ytd (no LOB axis)
  - Section-aware disambiguation: "(c) Others" maps to prov_others in the
    provisions section and is skipped in the expenses section (which uses
    "(g) Others" for exp_others and "(iii) Others" for exp_contribution_others)
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.company_registry import COMPANY_DISPLAY_NAMES
from config.row_registry import NL2_ROW_ALIASES, NL2_SKIP_PATTERNS
from extractor.models import NL2Data, NL2Extract
from extractor.normaliser import clean_number, normalise_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NL-2 page detection
# ---------------------------------------------------------------------------
_NL2_RE = re.compile(
    r"(FORM\s+NL[-\s]?2\b|PROFIT\s+AND\s+LOSS\s+ACCOUNT|NL-2-B-PL)",
    re.IGNORECASE,
)
_SMALL_PDF_PAGE_THRESHOLD = 4


def get_nl2_pages(pdf) -> list:
    """Return only the pages that belong to FORM NL-2."""
    all_pages = list(pdf.pages)
    if len(all_pages) <= _SMALL_PDF_PAGE_THRESHOLD:
        return all_pages

    nl2_pages = []
    for page in all_pages:
        text = page.extract_text() or ""
        if _NL2_RE.search(text):
            nl2_pages.append(page)

    if nl2_pages:
        return nl2_pages

    logger.warning("No FORM NL-2 header found; processing all pages")
    return all_pages


def resolve_company_name(company_key: str, pdf_path: str, fallback: str = "") -> str:
    """Resolve company display name with PDF-filename fallback."""
    name = COMPANY_DISPLAY_NAMES.get(company_key)
    if name:
        return name
    stem = Path(pdf_path).stem
    stem = re.sub(r'[_-](?:NL2|Q[1-4]|\d{6}|\d{4})$', '', stem, flags=re.IGNORECASE)
    words = re.sub(r'([a-z])([A-Z])', r'\1 \2', stem).replace('_', ' ').replace('-', ' ').split()
    if words:
        return ' '.join(words)
    return fallback or company_key.replace('_', ' ').title()


# ---------------------------------------------------------------------------
# Period column detection
# ---------------------------------------------------------------------------

# Patterns for the 4 NL-2 period header phrases
_CY_QTR_RE = re.compile(
    r"for\s+the\s+quarter\s+ended\s+(dec|sep|jun|mar|december|september|june|march)\s*\d{4}",
    re.IGNORECASE,
)
_CY_YTD_RE = re.compile(
    r"up\s+to\s+the\s+(period|quarter)\s+ended\s+(dec|sep|jun|mar|december|september|june|march)\s*\d{4}",
    re.IGNORECASE,
)
_PY_QTR_RE = re.compile(r"for\s+the\s+quarter\s+ended", re.IGNORECASE)
_PY_YTD_RE = re.compile(r"up\s+to\s+the\s+(period|quarter)\s+ended", re.IGNORECASE)

# Bare year extractor — used to distinguish CY vs PY when both match the same pattern
_YEAR_RE = re.compile(r'\b(20\d\d)\b')


def _extract_year(text: str) -> Optional[int]:
    """Extract the last 4-digit year from a cell text."""
    m = _YEAR_RE.findall(str(text or ""))
    return int(m[-1]) if m else None


def detect_period_columns(table) -> Dict[str, int]:
    """
    Scan the first 5 rows of a table for NL-2 period span labels.

    Returns a dict with keys: cy_qtr, cy_ytd, py_qtr, py_ytd
    mapping to 0-based column indices. Missing periods map to None.

    Strategy:
      1. Find all cells matching "For the quarter ended ..." and
         "Up to the period/quarter ended ...".
      2. Among those, the ones with the higher year = CY; lower year = PY.
      3. Within each period-type pair, the quarter cell comes before the YTD cell.
    """
    period_cols: Dict[str, Optional[int]] = {
        "cy_qtr": None, "cy_ytd": None,
        "py_qtr": None, "py_ytd": None,
    }

    qtr_candidates: List[Tuple[int, int, int]] = []   # (col_idx, year, row_idx)
    ytd_candidates: List[Tuple[int, int, int]] = []

    for ri, row in enumerate(table[:5]):
        for ci, cell in enumerate(row):
            if not cell:
                continue
            text = str(cell).replace("\n", " ").strip()
            year = _extract_year(text)
            if year is None:
                continue
            if _CY_QTR_RE.search(text) or (re.search(r"for\s+the\s+quarter\s+ended", text, re.I) and year):
                qtr_candidates.append((ci, year, ri))
            elif _CY_YTD_RE.search(text) or (re.search(r"up\s+to\s+the\s+(period|quarter)\s+ended", text, re.I) and year):
                ytd_candidates.append((ci, year, ri))

    if not qtr_candidates and not ytd_candidates:
        return period_cols

    # Assign CY = max year, PY = min year
    if qtr_candidates:
        qtr_candidates.sort(key=lambda x: x[1], reverse=True)
        period_cols["cy_qtr"] = qtr_candidates[0][0]
        if len(qtr_candidates) >= 2:
            period_cols["py_qtr"] = qtr_candidates[-1][0]

    if ytd_candidates:
        ytd_candidates.sort(key=lambda x: x[1], reverse=True)
        period_cols["cy_ytd"] = ytd_candidates[0][0]
        if len(ytd_candidates) >= 2:
            period_cols["py_ytd"] = ytd_candidates[-1][0]

    return period_cols


# ---------------------------------------------------------------------------
# Section-aware P&L row detection
# ---------------------------------------------------------------------------

# State machine section labels (detected from col 1, lowercased)
_SECTION_TRIGGERS = {
    "operating profit":             "operating",
    "income from investments":      "investments",
    "provisions (other than":       "provisions",
    "other expenses":               "expenses",
    "appropriations":               "appropriations",
}


def _matches_section_trigger(label: str) -> Optional[str]:
    """Return section name if label starts a new section, else None."""
    for trigger, section in _SECTION_TRIGGERS.items():
        if label.startswith(trigger):
            return section
    return None


def detect_pl_rows(table) -> Dict[int, str]:
    """
    Section-aware scan of table rows.  Returns a mapping of
    {row_index -> canonical_pl_key} for all data rows in the table.

    State machine:
      - Tracks current section (operating / investments / provisions /
        expenses / appropriations).
      - Uses section context to disambiguate identical labels:
          "(c) Others" in provisions section -> prov_others
          "(iii) Others" in expenses section -> exp_contribution_others
          "(g) Others" in expenses section   -> exp_others
      - Section header rows are NOT assigned a metric key (they are skipped).
      - Rows matching NL2_SKIP_PATTERNS are always skipped.

    Labels are read from col 1 (col 0 has serial numbers).
    If col 1 is blank, falls back to col 0.
    """
    pl_rows: Dict[int, str] = {}
    section: Optional[str] = None

    for ri, row in enumerate(table):
        if not row:
            continue

        # Read label from col 1 first (NL-2 has S.No in col 0)
        raw_1 = (row[1] or "") if len(row) > 1 else ""
        raw_0 = (row[0] or "")
        raw = raw_1.strip() if raw_1.strip() else raw_0.strip()
        if not raw:
            continue

        # Normalise: lowercase, strip asterisks, collapse whitespace
        label = re.sub(r'\s+', ' ', raw.replace("\n", " ")).strip().lower()
        label = label.rstrip('*').strip()

        # Section transition detection — must run BEFORE skip patterns so that
        # section headers update the state machine even though they carry no data.
        new_section = _matches_section_trigger(label)
        if new_section is not None:
            section = new_section
            continue

        # Non-section rows: skip form titles, column headers, bare serials, etc.
        skip = False
        for pat in NL2_SKIP_PATTERNS:
            if pat.search(label):
                skip = True
                break
        if skip:
            continue

        # Ambiguous labels resolved by section context
        if label in ("(c) others", "others"):
            if section == "provisions":
                pl_rows[ri] = "prov_others"
            # In expenses section "(c) others" does not appear — skip if seen
            continue

        if label == "(iii) others":
            if section == "expenses":
                pl_rows[ri] = "exp_contribution_others"
            continue

        if label == "(g) others":
            if section == "expenses":
                pl_rows[ri] = "exp_others"
            continue

        # Standard alias lookup
        key = NL2_ROW_ALIASES.get(label)
        if key is not None:
            pl_rows[ri] = key
        else:
            # Try partial-match fallback for long labels (e.g. footnote asterisks
            # or minor OCR variants not yet in the alias table)
            for alias, canonical in NL2_ROW_ALIASES.items():
                if label.startswith(alias) or alias.startswith(label[:30]):
                    pl_rows[ri] = canonical
                    break

    return pl_rows


# ---------------------------------------------------------------------------
# Grid extraction
# ---------------------------------------------------------------------------

def extract_nl2_grid(
    table: list,
    pl_rows: Dict[int, str],
    period_cols: Dict[str, Optional[int]],
    nl2_data: "NL2Data",
) -> None:
    """
    For each (row_idx, pl_key) in pl_rows, extract the 4 period values
    from the corresponding period columns and store them in nl2_data.
    """
    for row_idx, pl_key in pl_rows.items():
        if row_idx >= len(table):
            continue
        row = table[row_idx]
        for period_key, col_idx in period_cols.items():
            if col_idx is None:
                continue
            if col_idx >= len(row):
                continue
            val = clean_number(row[col_idx])
            if pl_key not in nl2_data.data:
                nl2_data.data[pl_key] = {}
            nl2_data.data[pl_key][period_key] = val


# ---------------------------------------------------------------------------
# Generic header-driven parser
# ---------------------------------------------------------------------------

def parse_header_driven_nl2(
    pdf_path: str,
    company_key: str,
    company_name_fallback: str = "",
    quarter: str = "",
    year: str = "",
) -> "NL2Extract":
    """
    Generic NL-2 parser for standard single-table layouts.

    Handles:
      - 1-page / multi-page PDFs (all NL-2 pages are processed in sequence)
      - Labels in col 1 (col 0 = serial number)
      - 4-column period layout: CY Qtr / CY YTD / PY Qtr / PY YTD
      - Section-aware "(c) others" disambiguation via detect_pl_rows()

    Returns an NL2Extract populated from the first table that yields
    all 4 period columns. Raises no exceptions — returns empty extract on failure.
    """
    import pdfplumber

    company_name = resolve_company_name(company_key, pdf_path, company_name_fallback)

    extract = NL2Extract(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=company_name,
        form_type="NL2",
        quarter=quarter,
        year=year,
        data=NL2Data(),
    )

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in get_nl2_pages(pdf):
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    if not table or len(table) < 3:
                        continue
                    period_cols = detect_period_columns(table)
                    # Need at least cy_ytd to proceed
                    if period_cols.get("cy_ytd") is None:
                        continue
                    pl_rows = detect_pl_rows(table)
                    if not pl_rows:
                        continue
                    extract_nl2_grid(table, pl_rows, period_cols, extract.data)
                    logger.info(
                        f"Extracted {len(pl_rows)} P&L rows from "
                        f"{Path(pdf_path).name} | period_cols={period_cols}"
                    )
                    # NL-2 is typically a single table — stop after first match
                    return extract

    except Exception as e:
        logger.error(f"parse_header_driven_nl2 failed for {pdf_path}: {e}")

    if not extract.data.data:
        logger.warning(f"No P&L data extracted from {pdf_path}")

    return extract
