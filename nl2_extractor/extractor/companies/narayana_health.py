"""
Dedicated NL-2-B-PL parser for Narayana Health Insurance Limited.

The PDF uses a word-level text layout with no extractable tables.
This parser uses pdfplumber extract_words() with x-position column bands:

  Label   : 50 <= x0 < 290  (NL-schedule refs and leading serials stripped)
  CY YTD  : 290 <= x0 < 355  (Upto the Quarter, Dec 31 2025)
  CY Qtr  : 355 <= x0 < 430  (For the Quarter, Dec 31 2025)
  PY Qtr  : 430 <= x0 < 510  (For the Quarter, Dec 31 2024)
  PY YTD  : x0 >= 510         (Upto the Quarter, Dec 31 2024)

Column order in this PDF: CY YTD | CY Qtr | PY Qtr | PY YTD
(Narayana's form puts "Upto the Quarter" before "For the Quarter")

Some rows have garbled PDF text (bleed-through from adjacent pages) and
are identified by y-position instead of label matching.
Space-broken numbers such as "6  2.82" (rendered as two PDF words) are
handled by joining band words with a space and passing to clean_number(),
which repairs digit-space-digit sequences (e.g. "6 2.82" → 62.82).
"""

import re
import os
import logging
from typing import Dict, Optional

import pdfplumber

from extractor.normaliser import clean_number
from extractor.models import NL2Data, NL2Extract
from extractor.companies._base_nl2 import resolve_company_name, _derive_other_expenses
from config.row_registry import NL2_ROW_ALIASES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column x-boundaries (determined from PDF inspection)
# ---------------------------------------------------------------------------
_LABEL_MIN_X = 50.0
_LABEL_MAX_X = 290.0
_CY_YTD_MIN  = 290.0
_CY_YTD_MAX  = 355.0
_CY_QTR_MIN  = 355.0
_CY_QTR_MAX  = 430.0
_PY_QTR_MIN  = 430.0
_PY_QTR_MAX  = 510.0
_PY_YTD_MIN  = 510.0

# Y-tolerance for grouping words on the same logical row
_Y_TOL = 5

# Strip schedule references: NL-1, NL-4A, etc.
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

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=2, y_tolerance=3)
                if not words:
                    continue

                rows = _group_words_by_row(words)

                for y_pos, row_words in rows.items():
                    # Extract values from each column band
                    cy_ytd = clean_number(_band_text(row_words, _CY_YTD_MIN, _CY_YTD_MAX)) \
                             if _band_text(row_words, _CY_YTD_MIN, _CY_YTD_MAX) else None
                    cy_qtr = clean_number(_band_text(row_words, _CY_QTR_MIN, _CY_QTR_MAX)) \
                             if _band_text(row_words, _CY_QTR_MIN, _CY_QTR_MAX) else None
                    py_qtr = clean_number(_band_text(row_words, _PY_QTR_MIN, _PY_QTR_MAX)) \
                             if _band_text(row_words, _PY_QTR_MIN, _PY_QTR_MAX) else None
                    py_ytd_txt = _band_text(row_words, _PY_YTD_MIN, float("inf"))
                    py_ytd = clean_number(py_ytd_txt) if py_ytd_txt else None

                    # Skip rows that carry no numeric data
                    if all(v is None for v in (cy_ytd, cy_qtr, py_qtr, py_ytd)):
                        continue

                    # 1. Y-position override (garbled label rows)
                    override = _y_override(y_pos)
                    if override == "__skip__":
                        continue
                    if override != "__miss__":
                        _set_period(nl2_data, override, cy_ytd, cy_qtr, py_qtr, py_ytd)
                        continue

                    # 2. Normal label → alias lookup
                    label = _label_text(row_words)
                    if not label:
                        continue
                    canon_key = NL2_ROW_ALIASES.get(label)
                    if canon_key is None:
                        logger.debug(
                            f"parse_narayana_nl2: unmatched label '{label}' at y={y_pos:.0f}"
                        )
                        continue

                    _set_period(nl2_data, canon_key, cy_ytd, cy_qtr, py_qtr, py_ytd)

    except Exception as e:
        logger.error(f"parse_narayana_nl2 failed for {pdf_path}: {e}", exc_info=True)

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
