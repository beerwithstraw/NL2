"""
Parser for Raheja QBE General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 2 pages, 3 tables each.
  T0: top + channel section, fire→total_health (23c)
      LOB header at row 4 (CY) or row 5 (PY) — detected dynamically.
      Data rows begin 2 rows after the LOB header row.
      Row 2 of CY T0 contains "Net Commission" in the registration block —
      avoided by starting metric detection at header_row + 2.
  T1: top section only, wc_el→grand_total (19c)
      LOB header at row 1. Data rows from row 3.
      Garbled OCR across both CY and PY (see _RAHEJA_EXTRA).
      Grand Total appears twice in header (col 17=qtr, col 18=ytd) — merged locally.
  T2: channel section for T1 LOBs (19c) — start_in_channel_section=True

Page 0: CY (Dec 31, 2025), Page 1: PY (Dec 31, 2024).

Garbled / truncated label variants across CY and PY T1:
  "Add: Commission on Re-insurance" (no "Accepted")  → ri_accepted_commission
  "Less: Commission on Re-insurance" (no "Ceded")    → ri_ceded_commission
  "ALecscse: Cteodmmission on Re-insurance"          → ri_ceded_commission (OCR mangled)
  "CNeedte Cdommission"                               → net_commission
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_lob_columns,
    detect_row_metrics,
    detect_calendar_year,
    extract_grid,
    match_header,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Raheja QBE General Insurance Company Limited"

# Raheja-specific garbled/truncated labels not caught by standard detector.
# Order matters: more-specific patterns first.
_RAHEJA_EXTRA: List[Tuple[str, str]] = [
    ("add: commission on re-insurance",  "ri_accepted_commission"),  # truncated (no "Accepted")
    ("less: commission on re-insurance", "ri_ceded_commission"),      # CY truncated (no "Ceded")
    ("cteodmmission",                    "ri_ceded_commission"),      # PY garbled OCR
    ("cneedte cdommission",              "net_commission"),
    ("cneete cdommission",               "net_commission"),
]


def _lob_header_row(table, min_lobs: int = 3) -> int:
    """Return the first row index where at least min_lobs cells (col 1+) match a LOB
    pattern. Requires multiple matches to skip single-cell category-span rows like
    the 'Miscellaneous' span that appears one row above the real LOB header."""
    for ri in range(min(8, len(table) - 1)):
        row = table[ri] or []
        count = sum(1 for c in row[1:] if c and c.strip() and match_header(c))
        if count >= min_lobs:
            return ri
    return 0


def _detect_metrics(table, start_row: int = 0, **kwargs) -> Dict[int, str]:
    """Run detect_row_metrics on table[start_row:], apply Raheja-specific extra
    patterns, then remap all indices back to the original table's numbering."""
    sliced = table[start_row:]
    metrics = detect_row_metrics(sliced, **kwargs)

    assigned = set(metrics.values())
    for ri, row in enumerate(sliced):
        if not row:
            continue
        label = (row[0] or "").replace("\n", " ").strip().lower()
        for pattern, metric_key in _RAHEJA_EXTRA:
            if pattern in label and metric_key not in assigned:
                metrics[ri] = metric_key
                assigned.add(metric_key)
                break

    return {ri + start_row: metric for ri, metric in metrics.items()}


def _merge_split_lobs(
    lob_cols: List[Tuple[str, Optional[int], Optional[int]]]
) -> List[Tuple[str, Optional[int], Optional[int]]]:
    """Merge duplicate LOB entries where one carries qtr_col and the other ytd_col.
    Handles grand_total split (col 17 = qtr, col 18 = ytd)."""
    merged: Dict[str, List] = {}
    order: List[str] = []
    for lob, qc, yc in lob_cols:
        if lob not in merged:
            merged[lob] = [qc, yc]
            order.append(lob)
        else:
            if qc is not None:
                merged[lob][0] = qc
            if yc is not None:
                merged[lob][1] = yc
    return [(lob, merged[lob][0], merged[lob][1]) for lob in order]


def parse_raheja_qbe(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Raheja QBE NL-6 PDF: {pdf_path}")
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

    page_data = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in get_nl6_pages(pdf):
            tables = page.extract_tables()
            if len(tables) < 3:
                continue
            t0, t1, t2 = tables[0], tables[1], tables[2]

            # T0: find LOB header row dynamically (CY=row 4, PY=row 5)
            hr_a = _lob_header_row(t0)
            lob_cols_a = _merge_split_lobs(detect_lob_columns(t0[hr_a:]))

            # T1: LOB header consistently at row 1
            hr_b = _lob_header_row(t1)
            lob_cols_b = _merge_split_lobs(detect_lob_columns(t1[hr_b:]))

            if not lob_cols_a or not lob_cols_b:
                continue

            # Slicing exposes period label row to detect_calendar_year
            # (avoids the "2008" registration year in T0 row 2)
            yr = detect_calendar_year(t0[hr_a:])
            page_data.append((yr, t0, t1, t2, lob_cols_a, lob_cols_b, hr_a, hr_b))

    if not page_data:
        logger.warning("Raheja QBE: no valid pages found")
        extract.current_year = cy
        extract.prior_year = py
        return extract

    years = [d[0] for d in page_data if d[0] is not None]
    max_year = max(years) if years else None

    for yr, t0, t1, t2, lob_cols_a, lob_cols_b, hr_a, hr_b in page_data:
        period_data = cy if (max_year and yr and yr >= max_year) else py

        # T0: skip LOB header row + period-label row before first data row
        rm0 = _detect_metrics(t0, start_row=hr_a + 2)
        if rm0:
            extract_grid(t0, rm0, lob_cols_a, period_data)

        # T1: skip LOB header row + period-label row
        rm1 = _detect_metrics(t1, start_row=hr_b + 2)
        if rm1:
            extract_grid(t1, rm1, lob_cols_b, period_data)

        # T2: channel section for T1 LOBs
        rm2 = detect_row_metrics(t2, start_in_channel_section=True)
        if rm2:
            extract_grid(t2, rm2, lob_cols_b, period_data)

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
