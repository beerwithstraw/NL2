"""
Parser for Universal Sompo General Insurance Company Limited (NL-6 Commission Schedule).

PDF Structure: 2 NL-6 pages, 4 tables per page.
  T0 = CY top section   (commission rows)
  T1 = CY channel       (channel breakdown, no boundary row)
  T2 = PY top section
  T3 = PY channel

Page 0 (23 cols): fire, marine_cargo, marine_hull, total_marine, motor_od, motor_tp,
  total_motor, health, personal_accident, travel_insurance, total_health (LOBs 1-22).
  T0 r0 has LOB names → detect_lob_columns works.
  T2 r0 has only garbled period headers (no LOB names) → reuse lob_cols from T0.

Page 1 (19 cols): wc_el, public_product_liability, engineering, aviation,
  crop_insurance, credit_insurance, other_miscellaneous, total_miscellaneous, grand_total.
  All tables r0 garbled → hardcoded column positions.

CY/PY: detect_period_year and detect_calendar_year both return None (garbled headers).
  Assignment by table position: T0/T1=CY, T2/T3=PY.

Channel note: r5 "MISP Broker" → misp_direct (alias added to _base_nl6.py).
"""

import logging
from pathlib import Path
from typing import List, Tuple

import pdfplumber

from extractor.models import CompanyExtract, PeriodData
from extractor.normaliser import clean_number
from extractor.companies._base_nl6 import (
    get_nl6_pages,
    resolve_company_name,
    detect_lob_columns,
    detect_row_metrics,
    extract_grid,
)

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "Universal Sompo General Insurance Company Limited"

# Page 1 LOBs — hardcoded because r0 has only garbled period labels
_PAGE2_LOBS: List[Tuple[str, int, int]] = [
    ("wc_el",                    1,  2),
    ("public_product_liability", 3,  4),
    ("engineering",              5,  6),
    ("aviation",                 7,  8),
    ("crop_insurance",           9,  10),
    ("credit_insurance",         11, 12),
    ("other_miscellaneous",      13, 14),
    ("total_miscellaneous",      15, 16),
    ("grand_total",              17, 18),
]


def parse_universal_sompo(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
) -> CompanyExtract:
    logger.info(f"Parsing Universal Sompo NL-6 PDF: {pdf_path}")
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
        pages = list(get_nl6_pages(pdf))

        for pi, page in enumerate(pages):
            tables = [t for t in page.extract_tables() if t and len(t) >= 4]
            if len(tables) < 4:
                logger.warning(f"Universal Sompo P{pi}: expected 4 tables, got {len(tables)}")
                continue

            t_cy_top, t_cy_ch, t_py_top, t_py_ch = tables[0], tables[1], tables[2], tables[3]

            # LOB columns: detect from CY top table (has LOB names in r0),
            # reuse for all 4 tables on this page.
            if pi == 0:
                lob_cols = detect_lob_columns(t_cy_top)
            else:
                lob_cols = _PAGE2_LOBS

            if not lob_cols:
                logger.warning(f"Universal Sompo P{pi}: no LOB cols")
                continue

            for top_t, ch_t, period_data in [
                (t_cy_top, t_cy_ch, cy),
                (t_py_top, t_py_ch, py),
            ]:
                rm_top = detect_row_metrics(top_t)
                if rm_top:
                    extract_grid(top_t, rm_top, lob_cols, period_data)

                rm_ch = detect_row_metrics(ch_t, start_in_channel_section=True)
                if rm_ch:
                    extract_grid(ch_t, rm_ch, lob_cols, period_data)

                # PY channel tables: pdfplumber merges "Other" and "TOTAL" rows
                # into r11 with stacked values ('-\n{total}').  Extract the
                # second \n-part as total_channel.
                if len(ch_t) > 11:
                    row = ch_t[11]
                    # Detect the merged row by \n in any data cell (not the label)
                    if any("\n" in (row[c] or "") for c in range(1, min(3, len(row)))):
                        for lob, qc, yc in lob_cols:
                            def _split_val(cell, idx):
                                if cell and "\n" in cell:
                                    parts = cell.split("\n")
                                    return clean_number(parts[idx]) if idx < len(parts) else None
                                return None
                            qv = _split_val(row[qc] if qc < len(row) else None, 1)
                            yv = _split_val(row[yc] if yc < len(row) else None, 1)
                            if qv is not None or yv is not None:
                                if lob not in period_data.data:
                                    period_data.data[lob] = {}
                                if "total_channel" not in period_data.data[lob]:
                                    period_data.data[lob]["total_channel"] = {"qtr": None, "ytd": None}
                                if qv is not None and period_data.data[lob]["total_channel"]["qtr"] is None:
                                    period_data.data[lob]["total_channel"]["qtr"] = qv
                                if yv is not None and period_data.data[lob]["total_channel"]["ytd"] is None:
                                    period_data.data[lob]["total_channel"]["ytd"] = yv

    logger.info(
        f"Extraction complete: CY {len(cy.data)} LOBs, PY {len(py.data)} LOBs."
    )
    extract.current_year = cy
    extract.prior_year = py
    return extract
