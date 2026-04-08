"""
Parser for Shriram General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 1 page, 2 tables. T0=CY, T1=PY. Each: 26r × 41c.

Column layout (r0): LOB names as col 0=Particulars, then LOB pairs (odd=qtr, even=ytd).
  Grand Total split: col 39=qtr only, col 40=ytd only.
  wc_el and other_miscellaneous headers are OCR-garbled in r0 — matched via local aliases.

Row layout: one metric per row, labels in col 0.
  r0:  LOB header row (partially garbled)
  r1:  Period label row (fully garbled — year extracted by stripping non-digits)
  r2:  Commission & Remuneration
  r3:  Rewards
  r4:  Distribution fees
  r5:  Gross Commission
  r6:  "AAdccde: pCtoemdmission on Re-insurance" (garbled RI Accepted)
  r7:  "LCeesdse:d Commission on Re-insurance"   (garbled RI Ceded)
  r8:  Net Commission
  r9:  Section boundary ("Break-up of the expenses...")
  r10: blank
  r11-r19: channel rows (Individual Agents → Common Service Centers)
  r20: "MPoicinrto oAf gSeanltess (Direct)" — Micro Agents (line 0) + Point of Sales (line 1), \n-stacked
  r21: Other (to be specified)
  r22: TOTAL
  r23-r25: footer (Commission written in India/Outside India, skip)

CY/PY: detect_period_year and detect_calendar_year both return None (garbled OCR).
  Year extracted by stripping all non-digits from r1 col1 → "2025" / "2024".
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
    detect_row_metrics,
    extract_grid,
    match_header,
    _SECTION_BOUNDARIES,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Shriram General Insurance Company Limited"

# LOB aliases for garbled r0 headers — Shriram-specific only
_SHRIRAM_LOB_ALIASES: List[Tuple[str, str]] = [
    ("ekm",     "wc_el"),               # garbled "WorEkmmpelno\u2019ys eCro\u2019sm..." (\u2019 splits "workm")
    ("mceell",  "other_miscellaneous"), # garbled "Other sMeigsmceellnatneous"
]

# Row metric aliases for garbled col 0 labels — Shriram-specific only
_SHRIRAM_ROW_ALIASES: List[Tuple[str, str]] = [
    ("aadccde",    "ri_accepted_commission"),  # "AAdccde: pCtoemdmission on Re-insurance"
    ("lceesdse",   "ri_ceded_commission"),     # "LCeesdse:d Commission on Re-insurance"
    ("mpoicinrto", "micro_agent"),             # first line of stacked r20
]


def _extract_year(table) -> Optional[int]:
    """Extract 4-digit year from garbled period label row by keeping only digits."""
    if not table or len(table) < 2:
        return None
    cell = table[1][1] if len(table[1]) > 1 else None
    if not cell:
        return None
    digits = re.sub(r'[^0-9]', '', cell)
    m = re.search(r'20\d\d', digits)
    return int(m.group()) if m else None


def _parse_shriram_lob_cols(row0) -> List[Tuple[str, int, int]]:
    """Build (lob_key, qtr_col, ytd_col) from r0 only, using local garbled aliases
    for cells that don't match the standard HEADER_TO_LOB patterns."""
    lob_cols: List[Tuple[str, int, int]] = []
    ci = 1
    while ci < len(row0):
        cell = (row0[ci] or "").strip()
        if not cell:
            ci += 1
            continue

        # Try standard match first
        lob = match_header(cell)

        # Fall back to local garbled aliases
        if lob is None:
            cell_lc = cell.lower()
            for fragment, key in _SHRIRAM_LOB_ALIASES:
                if fragment in cell_lc:
                    lob = key
                    break

        if lob is None:
            ci += 1
            continue

        # Next column is the ytd pair (None cell = span continuation)
        ytd_ci = ci + 1 if (ci + 1 < len(row0) and not (row0[ci + 1] or "").strip()) else None
        if ytd_ci is not None:
            lob_cols.append((lob, ci, ytd_ci))
            ci = ytd_ci + 1
        else:
            lob_cols.append((lob, ci, None))
            ci += 1

    # Grand Total appears twice (col 39=qtr only, col 40=ytd only) — merge them.
    # When a lob already has a qtr_col and the second entry also carries only a
    # qtr_col (ytd=None), treat the second qtr_col as the ytd_col.
    merged: Dict[str, List] = {}
    order: List[str] = []
    for lob, qc, yc in lob_cols:
        if lob not in merged:
            merged[lob] = [qc, yc]
            order.append(lob)
        else:
            existing_qc, existing_yc = merged[lob]
            if yc is not None:
                merged[lob][1] = yc
            elif qc is not None:
                # Second occurrence also has only qtr_col — use as ytd_col
                if existing_yc is None:
                    merged[lob][1] = qc
                else:
                    merged[lob][0] = qc
    return [(lob, merged[lob][0], merged[lob][1]) for lob in order]


def _detect_metrics_shriram(table) -> Dict[int, str]:
    """Run standard detect_row_metrics, then patch in Shriram-specific garbled labels."""
    metrics = detect_row_metrics(table)
    assigned = set(metrics.values())

    for ri, row in enumerate(table):
        if not row:
            continue
        label = (row[0] or "").replace("\n", " ").strip()
        if not label:
            continue
        label_lc = label.lower()

        # Section boundary check
        if any(b in label_lc for b in _SECTION_BOUNDARIES):
            break  # channel section handled by detect_row_metrics already

        for fragment, key in _SHRIRAM_ROW_ALIASES:
            if fragment in label_lc and key not in assigned and ri not in metrics:
                metrics[ri] = key
                assigned.add(key)
                break

    # r20: stacked "Micro Agents\nPoint of Sales" — detect_row_metrics won't see this
    # Handle below in _extract_table_shriram directly
    return metrics


def _extract_table_shriram(
    table,
    lob_cols: List[Tuple[str, int, int]],
    period_data: PeriodData,
) -> None:
    """Extract from a Shriram table: standard rows via detect_row_metrics +
    Shriram aliases, plus r20 stacked Micro Agents / Point of Sales."""
    row_metrics = _detect_metrics_shriram(table)

    # Standard extraction via extract_grid
    extract_grid(table, row_metrics, lob_cols, period_data)

    # r21: "Other (to be specified)" — cell contains "value\n-" (PDF stacks a blank
    # sub-row). clean_number fails on the full cell; take only the first \n-split part.
    if len(table) > 21:
        row = table[21]
        for lob, qc, yc in lob_cols:
            qtr_parts = [p.strip() for p in (row[qc] or "").split("\n")] if qc is not None and qc < len(row) else []
            ytd_parts = [p.strip() for p in (row[yc] or "").split("\n")] if yc is not None and yc < len(row) else []
            qv = clean_number(qtr_parts[0]) if qtr_parts else None
            yv = clean_number(ytd_parts[0]) if ytd_parts else None
            if qv is None and yv is None:
                continue
            if lob not in period_data.data:
                period_data.data[lob] = {}
            if "other_channels" not in period_data.data[lob]:
                period_data.data[lob]["other_channels"] = {"qtr": None, "ytd": None}
            if qv is not None and period_data.data[lob]["other_channels"]["qtr"] is None:
                period_data.data[lob]["other_channels"]["qtr"] = qv
            if yv is not None and period_data.data[lob]["other_channels"]["ytd"] is None:
                period_data.data[lob]["other_channels"]["ytd"] = yv

    # r20: "MPoicinrto oAf gSeanltess (Direct)" — stacks micro_agent (line 0)
    # and point_of_sales (line 1) in each data cell
    if len(table) > 20:
        row = table[20]
        stacked_metrics = ["micro_agent", "point_of_sales"]
        for lob, qc, yc in lob_cols:
            qtr_vals = [p.strip() for p in (row[qc] or "").split("\n")] if qc is not None and qc < len(row) else []
            ytd_vals = [p.strip() for p in (row[yc] or "").split("\n")] if yc is not None and yc < len(row) else []

            for idx, metric in enumerate(stacked_metrics):
                qv = clean_number(qtr_vals[idx]) if idx < len(qtr_vals) else None
                yv = clean_number(ytd_vals[idx]) if idx < len(ytd_vals) else None
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


def parse_shriram_general(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Shriram General NL-6 PDF: {pdf_path}")
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
            for t in page.extract_tables():
                if not t or len(t) < 5:
                    continue
                lob_cols = _parse_shriram_lob_cols(t[0])
                if not lob_cols:
                    continue
                yr = _extract_year(t)
                table_data.append((yr, t, lob_cols))

    if not table_data:
        logger.warning("Shriram General: no valid tables found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [d[0] for d in table_data if d[0] is not None]
    max_year = max(years) if years else None

    for yr, t, lob_cols in table_data:
        period_data = cy if (max_year and yr and yr >= max_year) else py
        _extract_table_shriram(t, lob_cols, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
