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

# Quarter keyword pattern — matches "for [the] quarter|period [ended]" as well as
# fiscal shorthand like "For Q3 2025-26" and plain "QUARTER ENDED ..."
_QTR_KEYWORD_RE = re.compile(
    r"(for\b.*?\bquarter|for\b.*?\bq[1-4]|quarter\b.*?\bended)",
    re.IGNORECASE,
)
# YTD keyword pattern — matches "up[to] [the] quarter|period|H1|H2" and fiscal "Upto Q3/9M"
# H1/H2 covers "Upto H1 2025-26" (ICICI Lombard Q2)
# half year covers "HALF YEAR ENDED 30TH SEPTEMBER 2025" (IFFCO Tokio Q2)
_YTD_KEYWORD_RE = re.compile(
    r"(up\s*to\b.*?\b(quarter|period|h[12])|upto\b.*?\b(quarter|period|h[12])|"
    r"up\s*to\b.*?\bq[1-4]|upto\b.*?\bq[1-4]|upto\b.*?\b\d+m\b|period\b.*?\bended|"
    r"half[\s-]*year\b)",
    re.IGNORECASE,
)

# Month abbreviation map for 2-digit year expansion
_MONTH_ABBR_RE = re.compile(r'[A-Za-z]{3}[-\'](\d{2})\b')
_FISCAL_YEAR_RE = re.compile(r'20(\d{2})-(\d{2})')
_DATE_DDMMYYYY_RE = re.compile(r'\d{1,2}\.\d{1,2}\.(20\d{2})')
_BARE_YEAR_RE = re.compile(r'\b(20\d{2})\b')


def _resolve_period_cell(text: str) -> Optional[int]:
    """
    Extract a 4-digit year from a period header cell string.
    Tries parsers in priority order; returns None if no year can be resolved.

    Priority:
      1. Bare 4-digit year (20xx)
      2. DD.MM.YYYY date format
      3. Mon-YY / Mon'YY abbreviation (Dec-25 → 2025)
      4. Fiscal year 20YY-ZZ → anchor year 20YY
      5. Returns None (Q3 with no year, etc.)
    """
    # 1. Bare 4-digit year — most common
    m = _BARE_YEAR_RE.findall(text)
    if m:
        return int(m[-1])
    # 2. DD.MM.YYYY
    m = _DATE_DDMMYYYY_RE.search(text)
    if m:
        return int(m.group(1))
    # 3. Mon-YY / Mon'YY
    m = _MONTH_ABBR_RE.search(text)
    if m:
        yy = int(m.group(1))
        return yy + 2000 if yy < 50 else yy + 1900
    # 4. Fiscal year 20YY-ZZ
    m = _FISCAL_YEAR_RE.search(text)
    if m:
        return int("20" + m.group(1))
    return None


def _expand_stacked_rows(table: list) -> list:
    """
    Expand rows where pdfplumber collapsed multiple P&L rows into a single
    newline-separated cell (e.g. "income from investments\n(a) interest...\n(b) profit...").

    Heuristic: if col 1 (label col) contains ≥2 newlines AND any sub-line
    matches a known NL2 alias, split on newlines and emit one virtual row per sub-label.
    Falls back to col 0 if col 1 is blank.
    """
    expanded = []
    for row in table:
        # Find the label column (prefer col 1, fallback col 0)
        label_col = None
        best_parts: list = []
        for ci in range(min(3, len(row))):
            cell = str(row[ci] or "")
            if cell.count('\n') >= 2:
                parts = [p.strip() for p in cell.split('\n') if p.strip()]
                if any(NL2_ROW_ALIASES.get(re.sub(r'\s+', ' ', p.lower()).rstrip('*').strip())
                       for p in parts):
                    label_col = ci
                    best_parts = parts
                    break

        if label_col is None or len(best_parts) < 2:
            expanded.append(row)
            continue

        # Split data columns at the same positions
        data_cols: Dict[int, list] = {}
        for ci in range(len(row)):
            if ci == label_col:
                continue
            cell_str = str(row[ci] or "")
            parts = [p.strip() for p in cell_str.split('\n') if p.strip()]
            data_cols[ci] = parts

        for idx, sub_label in enumerate(best_parts):
            virtual_row = [""] * len(row)
            virtual_row[label_col] = sub_label
            for ci, parts in data_cols.items():
                virtual_row[ci] = parts[idx] if idx < len(parts) else ""
            expanded.append(virtual_row)

    return expanded


def detect_period_columns(table) -> Dict[str, int]:
    """
    Scan the first 5 rows of a table for NL-2 period span labels.

    Returns a dict with keys: cy_qtr, cy_ytd, py_qtr, py_ytd
    mapping to 0-based column indices. Missing periods map to None.

    Strategy:
      1. Classify each cell as QTR or YTD via keyword patterns.
      2. Extract a year via _resolve_period_cell (handles 4-digit, DD.MM.YYYY,
         Mon-YY, fiscal 20YY-ZZ formats).
      3. CY = max year, PY = min year. If no year found, fall back to column
         position (first QTR = cy_qtr, second QTR = py_qtr, etc.).
    """
    period_cols: Dict[str, Optional[int]] = {
        "cy_qtr": None, "cy_ytd": None,
        "py_qtr": None, "py_ytd": None,
    }

    qtr_candidates: List[Tuple[int, int, int]] = []   # (col_idx, year_or_0, row_idx)
    ytd_candidates: List[Tuple[int, int, int]] = []

    # Increased from table[:5] to table[:15] to handle filings with long metadata headers (e.g. Universal Sompo)
    for ri, row in enumerate(table[:15]):
        for ci, cell in enumerate(row):
            # Skip the serial-number and label columns — their cells can accidentally
            # contain period keywords if the form title is merged into col 0/1.
            if ci < 2:
                continue
            if not cell:
                continue
            text = str(cell).replace("\n", " ").strip()
            is_qtr = bool(_QTR_KEYWORD_RE.search(text))
            is_ytd = bool(_YTD_KEYWORD_RE.search(text))
            if not is_qtr and not is_ytd:
                continue
            year = _resolve_period_cell(text) or 0
            # "Up to the Quarter Ended" matches both; YTD takes priority
            if is_ytd:
                ytd_candidates.append((ci, year, ri))
            else:
                qtr_candidates.append((ci, year, ri))

    if not qtr_candidates and not ytd_candidates:
        return period_cols

    # Assign CY = max year, PY = min year; if year=0 use column order
    if qtr_candidates:
        qtr_candidates.sort(key=lambda x: (x[2], x[0]))  # stable: row then col order
        if qtr_candidates[0][1] > 0:
            qtr_candidates.sort(key=lambda x: x[1], reverse=True)
        period_cols["cy_qtr"] = qtr_candidates[0][0]
        if len(qtr_candidates) >= 2:
            period_cols["py_qtr"] = qtr_candidates[-1][0]

    if ytd_candidates:
        ytd_candidates.sort(key=lambda x: (x[2], x[0]))
        if ytd_candidates[0][1] > 0:
            ytd_candidates.sort(key=lambda x: x[1], reverse=True)
        period_cols["cy_ytd"] = ytd_candidates[0][0]
        if len(ytd_candidates) >= 2:
            period_cols["py_ytd"] = ytd_candidates[-1][0]

    if any(v is not None for v in period_cols.values()) and qtr_candidates and qtr_candidates[0][1] == 0:
        logger.warning("Period columns detected by position only (no year found in header)")

    return period_cols


# ---------------------------------------------------------------------------
# Section-aware P&L row detection
# ---------------------------------------------------------------------------

# State machine section labels (detected from col 1, lowercased)
# Matches "(letter)[space*][for ]others[anything]" — section-aware prov_others detection
_PROV_OTHERS_RE = re.compile(r"^\([a-z]\)\s*(for\s+)?others", re.IGNORECASE)

_SECTION_TRIGGERS = {
    "operating profit":             "operating",
    "income from investments":      "investments",
    "provisions (other than":       "provisions",
    "other expenses":               "expenses",
    "(b) other expenses":           "expenses",
    "(c) other expenses":           "expenses",
    "b. other expenses":            "expenses",
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
        # Fallback to col 0 if col 1 is blank.
        # Fallback to col 2 (newly added for Aditya Birla where labels follow S.No in col 1)
        raw_1 = (row[1] or "") if len(row) > 1 else ""
        raw_0 = (row[0] or "")
        raw_2 = (row[2] or "") if len(row) > 2 else ""

        if raw_1.strip():
            raw = raw_1.strip()
        elif raw_0.strip():
            raw = raw_0.strip()
        else:
            raw = raw_2.strip()

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

        # Standard alias lookup — runs BEFORE prov_others and section-skip so that
        # explicitly aliased rows (e.g. "(c) others(other income)") are captured first.
        key = NL2_ROW_ALIASES.get(label)
        if key is not None:
            pl_rows[ri] = key
            continue

        # Partial-match fallback for long labels with footnote asterisks / OCR variants
        matched = False
        for alias, canonical in NL2_ROW_ALIASES.items():
            if label.startswith(alias) or alias.startswith(label[:30]):
                pl_rows[ri] = canonical
                matched = True
                break
        if matched:
            continue

        # Provisions "others" — section-aware disambiguation.
        # Only reached if no alias matched (explicit aliases like "(c) others(other income)"
        # are handled above).
        if _PROV_OTHERS_RE.match(label):
            if section == "provisions":
                pl_rows[ri] = "prov_others"
            # Otherwise (investments / expenses sub-items) — skip
            continue

        # Expense sub-items with no alias: skip — other_expenses is reverse-calculated
        if section == "expenses":
            continue

    return pl_rows


# ---------------------------------------------------------------------------
# Grid extraction
# ---------------------------------------------------------------------------

_ACCUMULATE_KEYS = {"other_income", "provision_taxation"}


def extract_nl2_grid(
    table: list,
    pl_rows: Dict[int, str],
    period_cols: Dict[str, Optional[int]],
    nl2_data: "NL2Data",
) -> None:
    """
    For each (row_idx, pl_key) in pl_rows, extract the 4 period values
    from the corresponding period columns and store them in nl2_data.

    Keys in _ACCUMULATE_KEYS are summed across multiple rows (e.g. other_income
    has sub-items; provision_taxation has current + deferred components).
    All other keys use last-write-wins (single canonical row expected).
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
            if pl_key in _ACCUMULATE_KEYS and val is not None:
                existing = nl2_data.data[pl_key].get(period_key)
                nl2_data.data[pl_key][period_key] = round((existing or 0.0) + val, 4)
            else:
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
            nl2_pages = get_nl2_pages(pdf)
            # Pass 1: try each table on each page
            found = False
            for page in nl2_pages:
                if found:
                    break
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    if not table or len(table) < 3:
                        continue
                    expanded = _expand_stacked_rows(table)
                    period_cols = detect_period_columns(expanded)
                    if period_cols.get("cy_ytd") is None:
                        continue
                    pl_rows = detect_pl_rows(expanded)
                    if not pl_rows:
                        continue
                    extract_nl2_grid(expanded, pl_rows, period_cols, extract.data)
                    logger.info(
                        f"Extracted {len(pl_rows)} P&L rows from "
                        f"{Path(pdf_path).name} | period_cols={period_cols}"
                    )
                    found = True
                    break

            # Pass 2: if still no data, scan raw page text for period keywords and
            # re-try table extraction with a synthetic header row injected from text.
            # This handles filings where the period header sits outside the table grid.
            if not found:
                for page in nl2_pages:
                    raw_text = page.extract_text() or ""
                    # Build a synthetic 1-row header from any line that has period keywords
                    header_cells = []
                    for line in raw_text.splitlines():
                        line = line.strip()
                        if _QTR_KEYWORD_RE.search(line) or _YTD_KEYWORD_RE.search(line):
                            header_cells.append(line)
                    if not header_cells:
                        continue
                    tables = page.extract_tables()
                    if not tables:
                        continue
                    for table in tables:
                        if not table or len(table) < 3:
                            continue
                        expanded = _expand_stacked_rows(table)
                        # Inject synthetic header row and try period detection on it
                        synthetic_row = ([""] * len(expanded[0]))
                        # Distribute header cells across non-label columns
                        data_cols = [ci for ci in range(len(synthetic_row)) if ci > 1]
                        for i, hcell in enumerate(header_cells):
                            if i < len(data_cols):
                                synthetic_row[data_cols[i]] = hcell
                        augmented = [synthetic_row] + expanded
                        period_cols = detect_period_columns(augmented)
                        if period_cols.get("cy_ytd") is None:
                            continue
                        pl_rows = detect_pl_rows(expanded)
                        if not pl_rows:
                            continue
                        extract_nl2_grid(expanded, pl_rows, period_cols, extract.data)
                        logger.info(
                            f"Extracted {len(pl_rows)} P&L rows (text-header fallback) from "
                            f"{Path(pdf_path).name} | period_cols={period_cols}"
                        )
                        found = True
                        break
                    if found:
                        break
    except Exception as e:
        logger.error(f"parse_header_driven_nl2 failed for {pdf_path}: {e}")

    # Structural derivations based on accounting identities
    _derive_other_income(extract.data)
    _derive_other_expenses(extract.data)
    _derive_provision_taxation(extract.data)

    if not extract.data.data:
        logger.warning(f"No P&L data extracted from {pdf_path}")

    return extract


def _derive_other_expenses(nl2_data: "NL2Data") -> None:
    """
    other_expenses = total_b - prov_diminution - prov_doubtful_debts - prov_others

    Computed for all four period slots. Absent provision items default to 0.
    """
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        total_b = nl2_data.data.get("total_b", {}).get(period)
        if total_b is None:
            continue
        prov_dim = nl2_data.data.get("prov_diminution", {}).get(period) or 0
        prov_dbt = nl2_data.data.get("prov_doubtful_debts", {}).get(period) or 0
        prov_oth = nl2_data.data.get("prov_others", {}).get(period) or 0
        other_exp = total_b - prov_dim - prov_dbt - prov_oth
        nl2_data.data.setdefault("other_expenses", {})[period] = round(other_exp, 4)


def _derive_other_income(nl2_data: "NL2Data") -> None:
    """
    other_income = total_a - op_profit - inv_income

    Where:
      op_profit = sum(op_fire, op_marine, op_miscellaneous)
      inv_income = inv_interest + inv_profit - inv_loss - inv_amortization

    Defaults to None if total_a is missing. Missing components default to 0.
    """
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        total_a = nl2_data.data.get("total_a", {}).get(period)
        if total_a is None:
            nl2_data.data.setdefault("other_income", {})[period] = None
            continue

        op_fire = nl2_data.data.get("op_fire", {}).get(period) or 0
        op_marine = nl2_data.data.get("op_marine", {}).get(period) or 0
        op_misc = nl2_data.data.get("op_miscellaneous", {}).get(period) or 0
        op_total = op_fire + op_marine + op_misc

        inv_int = nl2_data.data.get("inv_interest_dividend_rent", {}).get(period) or 0
        inv_prof = nl2_data.data.get("inv_profit_on_sale", {}).get(period) or 0
        inv_loss = nl2_data.data.get("inv_loss_on_sale", {}).get(period) or 0
        inv_amort = nl2_data.data.get("inv_amortization", {}).get(period) or 0
        inv_total = inv_int + inv_prof + inv_loss + inv_amort

        other_inc = total_a - op_total - inv_total
        nl2_data.data.setdefault("other_income", {})[period] = round(other_inc, 4)


def _derive_provision_taxation(nl2_data: "NL2Data") -> None:
    """
    provision_taxation = profit_before_tax - profit_after_tax

    Defaults to None if either PBT or PAT is missing.
    """
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        pbt = nl2_data.data.get("profit_before_tax", {}).get(period)
        pat = nl2_data.data.get("profit_after_tax", {}).get(period)

        if pbt is None or pat is None:
            # Highlight as None to signal derivation failure (per user request)
            nl2_data.data.setdefault("provision_taxation", {})[period] = None
        else:
            tax = pbt - pat
            nl2_data.data.setdefault("provision_taxation", {})[period] = round(tax, 4)
