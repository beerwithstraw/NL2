"""
Dedicated NL-2-B-PL parser for Narayana Health Insurance Limited.

The PDF uses a word-level text layout with no extractable tables.
Column positions vary by quarter, so this parser detects them dynamically
from the header row by locating "Upto" / "For" keywords and year labels.

  Q3 (Dec 2025) column order: CY YTD | CY Qtr | PY Qtr | PY YTD
  Q2 (Sep 2025) column order: CY YTD | CY Qtr | PY YTD | PY Qtr
  Q1 (Jun 2025) column order: CY Qtr | PY Qtr  (no separate YTD; copy qtr→ytd)

Some rows have garbled PDF text (bleed-through from adjacent pages) and
are identified by y-position instead of label matching.
Space-broken numbers such as "6  2.82" (rendered as two PDF words) are
handled by joining band words with a space and passing to clean_number(),
which repairs digit-space-digit sequences (e.g. "6 2.82" → 62.82).
"""

import re
import os
import logging
from typing import Dict, List, Optional, Tuple

import pdfplumber

from extractor.normaliser import clean_number
from extractor.models import NL2Data, NL2Extract
from extractor.companies._base_nl2 import resolve_company_name, _derive_other_expenses
from config.row_registry import NL2_ROW_ALIASES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label column boundary (same across all quarters)
# ---------------------------------------------------------------------------
_LABEL_MIN_X = 50.0
_LABEL_MAX_X = 290.0

# Y-tolerance for grouping words on the same logical row
_Y_TOL = 5

# Strip schedule references: NL-2, NL-2A, etc.
_SCHEDULE_RE = re.compile(r"\bNL-\d+[A-Z]?\b", re.IGNORECASE)

# Strip leading serial number ("2 income from investments" → "income from investments")
_LEADING_SERIAL_RE = re.compile(r"^\d+\s+")

# Keys that are summed across multiple sub-rows
_ACCUMULATE_KEYS = {"other_income", "provision_taxation", "approp_transfer_reserves"}

# Y-position overrides for rows with garbled / ambiguous labels.
# Maps approximate y-center → canonical key (None = skip the row entirely).
_Y_OVERRIDES: Dict[float, Optional[str]] = {
    208.0: "inv_amortization",          # amortisation of premium/discount (garbled)
    235.0: "other_income",              # gain/(loss) on forex fluctuation (garbled)
    506.0: "balance_brought_forward",   # balance brought forward from previous year (garbled)
}
_Y_OVERRIDE_TOL = 4.0


# ---------------------------------------------------------------------------
# Dynamic column detection
# ---------------------------------------------------------------------------

def _detect_column_bands(
    words: list,
) -> Tuple[Dict[str, Tuple[float, float]], bool]:
    """
    Scan header words (y <= 145) to determine column x-bands.

    Returns:
      (bands, is_single_period)

    bands  — dict mapping each period key to (x_min, x_max):
               "cy_ytd", "cy_qtr", "py_ytd", "py_qtr"
    is_single_period — True when only 2 columns are found (Q1 filing);
               in that case cy_ytd==cy_qtr and py_ytd==py_qtr bands,
               and the caller should copy qtr values to ytd after extraction.

    Strategy:
      1. Collect year-word x-centers (2024/2025) sorted left-to-right.
      2. Collect "Upto" keyword x-positions to identify YTD columns:
         each "Upto" owns the nearest year-word to its right → YTD.
         Remaining year-words → QTR.
      3. Map to cy/py by year value; if both years match (Q1), use
         positional order (left = CY, right = PY) and mark single-period.
      4. Build bands as midpoints between adjacent column centres.

    This avoids the "EndedFor" merged-token ambiguity (Q3 artefact) by
    relying only on "Upto" (never on "For") for column-type inference.
    """
    header = [w for w in words if w["top"] <= 145]

    # Identify the column-date row: the first y-level (bucketed to 4px) that
    # contains TWO OR MORE year words in the data-column area (x >= _LABEL_MAX_X).
    # This avoids matching single year words in the document title line.
    _y_buckets: Dict[int, list] = {}
    for w in header:
        if w["text"] in ("2024", "2025") and w["x0"] >= _LABEL_MAX_X:
            yb = int(w["top"] / 4) * 4
            _y_buckets.setdefault(yb, []).append(w)
    col_header_y = min(
        (yb for yb, ws in _y_buckets.items() if len(ws) >= 2),
        default=0.0,
    )

    # Collect year-word x-centers from the column-date row (y >= col_header_y),
    # deduplicating by rounding to nearest 5px.
    year_xs: List[Tuple[float, int]] = []   # (x_center, year)
    seen_approx: set = set()
    for w in header:
        if w["text"] in ("2024", "2025") and w["top"] >= col_header_y:
            xc = (w["x0"] + w["x1"]) / 2
            approx = round(xc / 5) * 5
            if approx not in seen_approx:
                seen_approx.add(approx)
                year_xs.append((xc, int(w["text"])))

    if not year_xs:
        return {}, False

    year_xs.sort(key=lambda e: e[0])

    # Collect "Upto" keyword x-positions (these mark YTD column headers)
    upto_xs = [w["x0"] for w in header if w["text"].lower() == "upto"]
    upto_xs.sort()

    # Match each "Upto" to the nearest year-word to its right (≤ 200 px away)
    ytd_xs: set = set()
    for ux in upto_xs:
        candidates = [(xc, yr) for xc, yr in year_xs if 0 < xc - ux <= 200]
        if candidates:
            nearest = min(candidates, key=lambda e: e[0] - ux)
            ytd_xs.add(nearest[0])

    # Build period_key → x_center map
    all_years = {yr for _, yr in year_xs}
    is_single_period = (len(all_years) == 1 and len(year_xs) == 2)

    col_map: Dict[str, float] = {}

    if is_single_period:
        # Q1: both "For" columns, no "Upto"; left = CY, right = PY
        col_map["cy_qtr"] = year_xs[0][0]
        col_map["cy_ytd"] = year_xs[0][0]
        col_map["py_qtr"] = year_xs[1][0]
        col_map["py_ytd"] = year_xs[1][0]
    else:
        cy_year = max(all_years)
        for xc, yr in year_xs:
            prefix = "cy" if yr == cy_year else "py"
            col_type = "ytd" if xc in ytd_xs else "qtr"
            period = f"{prefix}_{col_type}"
            if period not in col_map:
                col_map[period] = xc

    if not col_map:
        return {}, False

    # Convert x-centers to (x_min, x_max) bands via midpoints;
    # deduplicate by x first (Q1 has cy_ytd==cy_qtr at same x)
    seen_x: Dict[float, str] = {}
    unique_cols: List[Tuple[str, float]] = []
    for period, x in sorted(col_map.items(), key=lambda kv: kv[1]):
        rounded = round(x, 1)
        if rounded not in seen_x:
            seen_x[rounded] = period
            unique_cols.append((period, x))

    xs = [c[1] for c in unique_cols]
    bands: Dict[str, Tuple[float, float]] = {}

    for i, (period, x) in enumerate(unique_cols):
        x_left  = (xs[i - 1] + x) / 2 if i > 0 else _LABEL_MAX_X
        x_right = (x + xs[i + 1]) / 2 if i < len(unique_cols) - 1 else float("inf")
        bands[period] = (x_left, x_right)

    # For Q1, duplicate bands so cy_ytd==cy_qtr and py_ytd==py_qtr
    if is_single_period:
        if "cy_qtr" in bands:
            bands["cy_ytd"] = bands["cy_qtr"]
        if "py_qtr" in bands:
            bands["py_ytd"] = bands["py_qtr"]

    logger.debug(
        f"parse_narayana_nl2: bands={bands} is_single_period={is_single_period}"
    )
    return bands, is_single_period


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_words_by_row(words: list) -> Dict[float, list]:
    """Group pdfplumber word dicts into rows by approximate y-position."""
    buckets: Dict[float, list] = {}
    for w in words:
        y = w["top"]
        matched = None
        for ky in buckets:
            if abs(ky - y) <= _Y_TOL:
                matched = ky
                break
        if matched is None:
            matched = y
        buckets.setdefault(matched, []).append(w)
    return {k: sorted(v, key=lambda w: w["x0"]) for k, v in sorted(buckets.items())}


def _band_text(row_words: list, x_min: float, x_max: float) -> str:
    """Collect words within [x_min, x_max) and join with a single space."""
    return " ".join(w["text"] for w in row_words if x_min <= w["x0"] < x_max)


def _label_text(row_words: list) -> str:
    """
    Extract the row label from words in [_LABEL_MIN_X, _LABEL_MAX_X).
    Strips NL-schedule references and leading serial numbers, lowercases.
    """
    raw = " ".join(w["text"] for w in row_words
                   if _LABEL_MIN_X <= w["x0"] < _LABEL_MAX_X)
    raw = _SCHEDULE_RE.sub("", raw)
    raw = _LEADING_SERIAL_RE.sub("", raw)
    return re.sub(r"\s+", " ", raw).strip().lower()


def _y_override(y: float) -> str:
    """
    Return the canonical key for a y-overridden row, '__skip__' if the row
    should be discarded, or '__miss__' if no override applies.
    """
    for y_center, canon in _Y_OVERRIDES.items():
        if abs(y - y_center) <= _Y_OVERRIDE_TOL:
            return canon if canon is not None else "__skip__"
    return "__miss__"


def _set_period(nl2_data: NL2Data, key: str,
                cy_ytd, cy_qtr, py_qtr, py_ytd) -> None:
    """
    Write (or accumulate for _ACCUMULATE_KEYS) period values into nl2_data.
    """
    if key not in nl2_data.data:
        nl2_data.data[key] = {}
    values = {"cy_ytd": cy_ytd, "cy_qtr": cy_qtr, "py_qtr": py_qtr, "py_ytd": py_ytd}
    if key in _ACCUMULATE_KEYS:
        for period, val in values.items():
            if val is not None:
                existing = nl2_data.data[key].get(period)
                nl2_data.data[key][period] = round((existing or 0.0) + val, 4)
    else:
        nl2_data.data[key].update(values)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_narayana_nl2(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> NL2Extract:
    company_name = resolve_company_name(company_key, pdf_path,
                                        "Narayana Health Insurance Limited")
    nl2_data = NL2Data()
    is_single_period = False

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=2, y_tolerance=3)
                if not words:
                    continue

                # Detect column bands from this page's header
                bands, is_single_period = _detect_column_bands(words)
                if not bands:
                    logger.warning(f"parse_narayana_nl2: could not detect columns in {pdf_path}")
                    continue

                cy_ytd_band = bands.get("cy_ytd", (0, 0))
                cy_qtr_band = bands.get("cy_qtr", (0, 0))
                py_qtr_band = bands.get("py_qtr", (0, 0))
                py_ytd_band = bands.get("py_ytd", (0, 0))

                rows = _group_words_by_row(words)

                for y_pos, row_words in rows.items():
                    # Extract values from each column band
                    def _val(band):
                        txt = _band_text(row_words, band[0], band[1])
                        return clean_number(txt) if txt else None

                    cy_ytd = _val(cy_ytd_band)
                    cy_qtr = _val(cy_qtr_band)
                    py_qtr = _val(py_qtr_band)
                    py_ytd = _val(py_ytd_band)

                    # Skip rows with no numeric data
                    if all(v is None for v in (cy_ytd, cy_qtr, py_qtr, py_ytd)):
                        continue

                    # 1. Attempt normal label → alias lookup first
                    label = _label_text(row_words)
                    canon_key = NL2_ROW_ALIASES.get(label) if label else None

                    # 2. Y-position override — only fires when label is absent or
                    #    unrecognised (garbled rows in Q3); a clean alias match wins.
                    if canon_key is None:
                        override = _y_override(y_pos)
                        if override == "__skip__":
                            continue
                        if override != "__miss__":
                            _set_period(nl2_data, override, cy_ytd, cy_qtr, py_qtr, py_ytd)
                            continue
                        # Truly unmatched — log and skip
                        if label:
                            logger.debug(
                                f"parse_narayana_nl2: unmatched label '{label}' at y={y_pos:.0f}"
                            )
                        continue

                    _set_period(nl2_data, canon_key, cy_ytd, cy_qtr, py_qtr, py_ytd)

    except Exception as e:
        logger.error(f"parse_narayana_nl2 failed for {pdf_path}: {e}", exc_info=True)

    # For Q1 filings the YTD period is identical to the quarter period.
    # The PDF only has one column per year, which lands in the cy_qtr / py_qtr
    # bands.  Copy those values into cy_ytd / py_ytd so completeness checks pass.
    if is_single_period:
        for row_data in nl2_data.data.values():
            if row_data.get("cy_ytd") is None and row_data.get("cy_qtr") is not None:
                row_data["cy_ytd"] = row_data["cy_qtr"]
            if row_data.get("py_ytd") is None and row_data.get("py_qtr") is not None:
                row_data["py_ytd"] = row_data["py_qtr"]

    # Derive other_expenses = total_b − prov_diminution − prov_doubtful_debts − prov_others
    _derive_other_expenses(nl2_data)

    logger.info(
        f"parse_narayana_nl2: extracted {len(nl2_data.data)} P&L rows "
        f"from {os.path.basename(pdf_path)}"
    )
    return NL2Extract(
        source_file=os.path.basename(pdf_path),
        company_key=company_key,
        company_name=company_name,
        form_type="NL2",
        quarter=quarter,
        year=year,
        data=nl2_data,
    )
