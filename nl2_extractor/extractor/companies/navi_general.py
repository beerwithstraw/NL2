"""
Parser for Navi General Insurance Limited (NL-6 Commission Schedule).

PDF Structure: 2 pages, 7 tables each.
  T0: title (skip)
  T1: top section (11r × 20c)
  T2: channel section (13r × 20c)  — start_in_channel_section=True
  T3: in-india rows (skip)
  T4: top section (11r × 20c)
  T5: channel section (13r × 20c)
  T6: in-india rows (skip)

Period assignment by position (period labels unreliable — PDF has mislabeling):
  P1 T1/T2 → CY qtr
  P1 T4/T5 → PY qtr
  P2 T1/T2 → CY ytd
  P2 T4/T5 → PY ytd

2-row LOB header: r0=category spans, r1=sub-LOBs.
  Merged rule: r1 value takes priority; fallback to r0.
  All 19 LOBs detected cleanly via match_header.

Each table has one column per LOB (no qtr/ytd pair within table).
Custom _extract_to_slot writes values into the specified "qtr"/"ytd" slot.

Channel: separate table (T2/T5), detect_row_metrics(start_in_channel_section=True).
LOB columns reused from adjacent top table.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    match_header,
    detect_row_metrics,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Navi General Insurance Limited"


def _parse_lob_cols(table) -> List[Tuple[str, int]]:
    """Build (lob_key, col_idx) list from 2-row header."""
    r0 = table[0] if table else []
    r1 = table[1] if len(table) > 1 else []
    lob_cols = []
    for ci in range(len(r0)):
        v1 = (r1[ci] if ci < len(r1) else None) or ""
        v0 = (r0[ci] or "")
        cell = v1.strip() or v0.strip()
        if not cell:
            continue
        lob = match_header(cell)
        if lob:
            lob_cols.append((lob, ci))
    return lob_cols


def _extract_to_slot(
    table,
    row_metrics,
    lob_cols: List[Tuple[str, int]],
    period_data: PeriodData,
    slot: str,
) -> None:
    """Write values from a single-column-per-LOB table into the given slot (qtr/ytd)."""
    for row_idx, metric in row_metrics.items():
        if row_idx >= len(table):
            continue
        row = table[row_idx]
        for lob, ci in lob_cols:
            val = clean_number(row[ci]) if ci < len(row) else None
            if val is None:
                continue
            if lob not in period_data.data:
                period_data.data[lob] = {}
            if metric not in period_data.data[lob]:
                period_data.data[lob][metric] = {"qtr": None, "ytd": None}
            if period_data.data[lob][metric][slot] is None:
                period_data.data[lob][metric][slot] = val


def _process_pair(top_t, ch_t, period_data: PeriodData, slot: str) -> None:
    lob_cols = _parse_lob_cols(top_t)
    if not lob_cols:
        return

    rm_top = detect_row_metrics(top_t)
    if rm_top:
        _extract_to_slot(top_t, rm_top, lob_cols, period_data, slot)

    if ch_t is not None:
        rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
        if rm_ch:
            _extract_to_slot(ch_t, rm_ch, lob_cols, period_data, slot)


def parse_navi_general(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Navi General NL-6 PDF: {pdf_path}")
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

    with pdfplumber.open(pdf_path) as pdf:
        pages = get_nl6_pages(pdf)
        if len(pages) < 2:
            logger.warning("Navi General: expected 2 pages")
            extract.current_year = cy
            extract.prior_year = py
            return extract

        for pi, (page, slot_cy, slot_py) in enumerate([
            (pages[0], "qtr", "qtr"),
            (pages[1], "ytd", "ytd"),
        ]):
            tables = page.extract_tables()
            # T1=top, T2=channel, T4=top, T5=channel (T0=title, T3/T6=in-india)
            if len(tables) > 2:
                _process_pair(tables[1], tables[2], cy, slot_cy)
            if len(tables) > 5:
                _process_pair(tables[4], tables[5], py, slot_py)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
