"""
Parser for ACKO General Insurance Limited (NL-6 Commission Schedule).

PDF Structure: 1 page, 4 tables.
  T0: CY data (10r x 40c)
  T1: CY footer (1r — "In India / Outside India", skip)
  T2: PY data (10r x 40c)
  T3: PY footer (1r — skip)

Column layout (T0/T2): col 0=serial numbers, col 1=labels, then LOB pairs (odd=qtr, even=ytd).
  merge_lob_header_rows() on rows 0-1 detects all 19 LOBs (cols 2-39).

Row layout: pdfplumber collapses multiple metric rows into single cells using \n separators.
  r3 col1: "Commission & Remuneration\nRewards\nDistribution fees"  → 3 metrics stacked
  r3 data:  "1\n-\n-"                                               → 3 values stacked
  r4 col1: "Gross Commission\nAdd : ...\nLess : ..."                → 3 metrics stacked
  r5 col1: "Net Commission"                                          → single metric, single value
  r7:       section boundary row (col 0 = "Break-up of the expenses...")
  r8 col1: all 12 channel labels stacked                            → 12 metrics stacked
  r9 col1: "Total"                                                  → total_channel

  Approach: split col 1 (and col 0 fallback) by \n to get label list,
  split each data cell by \n to get value list, pair positionally.

CY/PY: detect_period_year returns None (labels use "Dec-25" 2-digit year).
  T0 r2 col 2 = "For the\nQuarter\nDec-25" → _detect_year_2digit → 2025.
  T2 r2 col 2 = "For the\nQuarter\nDec-24" → 2024.
  Max year → CY.
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    merge_lob_header_rows,
    _TOP_LABEL_TO_METRIC,
    _CHANNEL_LABEL_TO_METRIC,
    _SECTION_BOUNDARIES,
    _SKIP_LABELS,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "ACKO General Insurance Limited"
_YEAR_2DIG_RE = re.compile(r'\b(\d{2})\s*$')


def _detect_year_2digit(table) -> Optional[int]:
    """Parse 2-digit year suffix from period label row (e.g. 'Dec-25' → 2025)."""
    if not table or len(table) < 3:
        return None
    for cell in table[2]:
        if not cell:
            continue
        m = _YEAR_2DIG_RE.search(cell.replace("\n", " ").strip())
        if m:
            return 2000 + int(m.group(1))
    return None


def _norm(text: str) -> str:
    """Normalise a label for metric matching."""
    return " ".join(re.sub(r'[^a-z0-9]', ' ', text.lower().strip()).split())


def _match_metric(label: str, pairs: List[Tuple[str, str]], assigned: set) -> Optional[str]:
    n = _norm(label)
    if not n or n in _SKIP_LABELS or n.startswith("-"):
        return None
    for pattern, key in pairs:
        if _norm(pattern) in n and key not in assigned:
            return key
    return None


def _extract_table(
    table,
    lob_cols: List[Tuple[str, int, int]],
    period_data: PeriodData,
) -> None:
    """Extract metrics from a stacked-cell Acko table into period_data."""
    in_channel = False
    assigned: set = set()

    for ri, row in enumerate(table):
        if not row:
            continue

        # Section boundary detection (col 0)
        col0 = (row[0] or "").replace("\n", " ").strip().lower()
        if any(b in col0 for b in _SECTION_BOUNDARIES):
            in_channel = True
            assigned = set()   # reset so channel metrics can be assigned
            continue

        # Label source: col 1 preferred, fall back to col 0
        label_cell = (row[1] or "").strip() if len(row) > 1 else ""
        if not label_cell:
            label_cell = col0

        if not label_cell:
            continue

        # Split stacked labels
        labels = [l.strip() for l in label_cell.split("\n") if l.strip()]
        if not labels:
            continue

        pairs = _CHANNEL_LABEL_TO_METRIC if in_channel else _TOP_LABEL_TO_METRIC

        # Map each sub-label to a metric key
        metrics: List[Optional[str]] = []
        for lbl in labels:
            key = _match_metric(lbl, pairs, assigned)
            metrics.append(key)
            if key:
                assigned.add(key)

        if not any(metrics):
            continue

        # Extract values for each LOB
        for lob, qc, yc in lob_cols:
            qtr_cell = (row[qc] or "") if qc is not None and qc < len(row) else ""
            ytd_cell = (row[yc] or "") if yc is not None and yc < len(row) else ""

            qtr_parts = [p.strip() for p in qtr_cell.split("\n")] if qtr_cell else []
            ytd_parts = [p.strip() for p in ytd_cell.split("\n")] if ytd_cell else []

            for idx, metric in enumerate(metrics):
                if metric is None:
                    continue

                qv = clean_number(qtr_parts[idx]) if idx < len(qtr_parts) else None
                yv = clean_number(ytd_parts[idx]) if idx < len(ytd_parts) else None

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


def parse_acko(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing ACKO NL-6 PDF: {pdf_path}")
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

    table_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            tables = page.extract_tables()
            # T1 and T3 are 1-row footer tables — skip them; process T0 and T2
            data_tables = [t for t in tables if t and len(t) > 3]
            for t in data_tables:
                lob_cols = merge_lob_header_rows(t)
                if not lob_cols:
                    continue
                yr = _detect_year_2digit(t)
                table_data.append((yr, t, lob_cols))

    if not table_data:
        logger.warning("ACKO: no valid tables found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [d[0] for d in table_data if d[0] is not None]
    max_year = max(years) if years else None

    for yr, t, lob_cols in table_data:
        period_data = cy if (max_year and yr and yr >= max_year) else py
        _extract_table(t, lob_cols, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
