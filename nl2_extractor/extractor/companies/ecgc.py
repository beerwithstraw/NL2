"""
Parser for ECGC Limited.

PDF Structure: 1 NL-6 page. pdfplumber table extraction merges all top-section
rows into a single cell, making row-level extraction impossible via tables.

Approach: word-level coordinate extraction.
  - Words are grouped by Y position (tolerance 4px) into lines.
  - Column x-boundaries are derived from the period header words
    ("For the Quarter" / "Up to the Quarter" + year).
  - Each label line (words with x < label_threshold) is matched to a metric.
  - Value words are assigned to the nearest column center.

Column layout (4 period columns, single LOB: other_miscellaneous):
  CY_qtr  CY_ytd  PY_qtr  PY_ytd
  Fiscal year label in header distinguishes CY vs PY columns.

Number format: ECGC uses Indian sub-lakh notation (e.g. "14,97.50") which
clean_number handles correctly.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    _TOP_LABEL_TO_METRIC,
    _CHANNEL_LABEL_TO_METRIC,
    _SECTION_BOUNDARIES,
    _SKIP_LABELS,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "ECGC Limited"
_Y_TOLERANCE = 4      # px — words within this Y range are on the same line
_LABEL_X_MAX = 420    # px — words left of this are label text
_FISCAL_YEAR_RE = re.compile(r'\b(20\d\d)\b')


def _group_by_y(words: list, tol: float = _Y_TOLERANCE) -> List[List[dict]]:
    """Group words into lines by Y proximity."""
    if not words:
        return []
    lines: List[List[dict]] = []
    current = [words[0]]
    ref_y = words[0]["top"]
    for w in words[1:]:
        if abs(w["top"] - ref_y) <= tol:
            current.append(w)
        else:
            lines.append(sorted(current, key=lambda w: w["x0"]))
            current = [w]
            ref_y = w["top"]
    lines.append(sorted(current, key=lambda w: w["x0"]))
    return lines


def _detect_columns(words: list) -> Optional[List[Tuple[str, float, int]]]:
    """
    Detect the 4 period column x-centers from individual year-number word positions.

    Strategy: the header spans multiple Y lines; each column has exactly one
    year word (20XX). Collect all year words, sort by x — the two higher-year
    words = CY (smaller x = qtr, larger x = ytd), the two lower-year = PY.

    Returns list of (period_key, x_center, year) sorted by x_center.
    """
    year_words = [
        w for w in words
        if _FISCAL_YEAR_RE.fullmatch(w["text"].strip())
    ]
    if len(year_words) < 4:
        logger.warning(f"ECGC: found only {len(year_words)} year words, expected 4")
        return None

    # Cluster year words by x proximity (within 15px) — collapse multi-line duplicates
    sorted_yw = sorted(year_words, key=lambda w: w["x0"])
    clusters: List[Dict] = []
    for w in sorted_yw:
        x = w["x0"]
        yr = int(w["text"].strip())
        if clusters and abs(x - clusters[-1]["x"]) < 15:
            pass  # duplicate — same column, ignore
        else:
            clusters.append({"x": x, "year": yr})

    if len(clusters) < 4:
        logger.warning(f"ECGC: only {len(clusters)} distinct year columns, expected 4")
        return None

    # Take the 4 rightmost distinct clusters (skip any leftmost that may be title)
    clusters = sorted(clusters, key=lambda c: c["x"])[-4:]

    cy_year = max(c["year"] for c in clusters)
    cy_cols = sorted([c for c in clusters if c["year"] == cy_year], key=lambda c: c["x"])
    py_cols = sorted([c for c in clusters if c["year"] != cy_year], key=lambda c: c["x"])

    result = [
        ("cy_qtr", float(cy_cols[0]["x"]), cy_year),
        ("cy_ytd", float(cy_cols[1]["x"]), cy_year),
        ("py_qtr", float(py_cols[0]["x"]), py_cols[0]["year"]),
        ("py_ytd", float(py_cols[1]["x"]), py_cols[1]["year"]),
    ]
    return result


def _assign_to_col(x: float, cols: List[Tuple[str, float, int]]) -> Optional[str]:
    """Assign a word x-position to the nearest column."""
    return min(cols, key=lambda c: abs(x - c[1]))[0]


def _match_metric(label: str, in_channel: bool) -> Optional[str]:
    pairs = _CHANNEL_LABEL_TO_METRIC if in_channel else _TOP_LABEL_TO_METRIC
    for pattern, key in pairs:
        if pattern in label:
            return key
    return None


def parse_ecgc(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> CompanyExtract:
    logger.info(f"Parsing ECGC PDF (coordinate-based): {pdf_path}")
    company_name = resolve_company_name(company_key, pdf_path, _FALLBACK_NAME)

    extract = CompanyExtract(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=company_name,
        form_type="NL6",
        quarter=quarter,
        year=year,
    )

    cy = PeriodData(period_label="current")
    py = PeriodData(period_label="prior")

    # ECGC has a single LOB (credit/export guarantee = other_miscellaneous)
    lob = "other_miscellaneous"

    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            words = page.extract_words(use_text_flow=False)
            if not words:
                continue

            lines = _group_by_y(words)
            cols = _detect_columns(words)
            if not cols:
                logger.error("ECGC: could not detect period columns")
                continue

            # Map period_key → PeriodData
            period_map = {
                "cy_qtr": (cy, "qtr"),
                "cy_ytd": (cy, "ytd"),
                "py_qtr": (py, "qtr"),
                "py_ytd": (py, "ytd"),
            }

            in_channel = False
            seen_metrics: Dict[str, bool] = {}

            for line in lines:
                if not line:
                    continue

                label_words = [w for w in line if w["x0"] < _LABEL_X_MAX]
                value_words = [w for w in line if w["x0"] >= _LABEL_X_MAX]

                if not label_words:
                    continue

                label = " ".join(w["text"] for w in label_words).strip().lower()
                label = re.sub(r"[^a-z0-9 :&\-]", " ", label)
                label = " ".join(label.split())

                if not label or label in _SKIP_LABELS or label.startswith("-"):
                    continue

                if any(b in label for b in _SECTION_BOUNDARIES):
                    in_channel = True
                    continue

                metric = _match_metric(label, in_channel)
                if not metric or metric in seen_metrics:
                    continue
                seen_metrics[metric] = True

                # Extract values and assign to period columns
                for vw in value_words:
                    val = clean_number(vw["text"])
                    if val is None:
                        continue
                    vx = vw["x0"] + (vw.get("x1", vw["x0"] + 10) - vw["x0"]) / 2
                    period_key = _assign_to_col(vx, cols)
                    if period_key not in period_map:
                        continue
                    pd, slot = period_map[period_key]
                    if lob not in pd.data:
                        pd.data[lob] = {}
                    if metric not in pd.data[lob]:
                        pd.data[lob][metric] = {"qtr": None, "ytd": None}
                    if pd.data[lob][metric][slot] is None:
                        pd.data[lob][metric][slot] = val

    logger.info(f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs.")
    extract.current_year = cy
    extract.prior_year = py
    return extract
