"""
Dedicated parser for ACKO General Insurance Limited -- NL-2-B-PL.
Handles stacked row alignment issues in the Appropriations section.
"""

import logging
import re
import pdfplumber
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from extractor.companies._base_nl2 import (
    get_nl2_pages,
    resolve_company_name,
    detect_period_columns,
    detect_pl_rows,
    extract_nl2_grid,
    _derive_other_income,
    _derive_other_expenses,
    _derive_provision_taxation,
    _matches_section_trigger,
)
from extractor.models import NL2Data, NL2Extract

logger = logging.getLogger(__name__)


def _expand_stacked_rows_acko(table: list) -> list:
    """
    ACKO-specific stacked row expander.
    Ensures section headers (e.g. 'Appropriations') do not consume data columns.
    """
    from config.row_registry import NL2_ROW_ALIASES
    
    expanded = []
    for row in table:
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

        # Alignment correction: Identify headers
        data_idx = 0
        for sub_label in best_parts:
            virtual_row = [""] * len(row)
            virtual_row[label_col] = sub_label
            
            # Normalise for section check
            norm_label = re.sub(r'\s+', ' ', sub_label.replace("\n", " ").lower()).rstrip('*').strip()
            is_header = bool(_matches_section_trigger(norm_label))
            
            # If it's a section header (e.g. "Appropriations"), assign no data and don't advance data_idx
            if not is_header:
                for ci, parts in data_cols.items():
                    virtual_row[ci] = parts[data_idx] if data_idx < len(parts) else ""
                data_idx += 1
            
            expanded.append(virtual_row)

    return expanded


def parse_acko_nl2(
    pdf_path: str,
    company_key: str,
    quarter: str = "",
    year: str = "",
):
    """ACKO dedicated parser that uses section-aware row expansion."""
    logger.info(f"Parsing ACKO NL2 (Dedicated): {pdf_path}")
    
    company_name = resolve_company_name(company_key, pdf_path, "ACKO General Insurance Limited")

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
            found = False
            for page in nl2_pages:
                if found: break
                tables = page.extract_tables()
                if not tables: continue
                for table in tables:
                    if not table or len(table) < 3: continue
                    # Use custom expansion logic
                    expanded = _expand_stacked_rows_acko(table)
                    period_cols = detect_period_columns(expanded)
                    if period_cols.get("cy_ytd") is None: continue
                    pl_rows = detect_pl_rows(expanded)
                    if not pl_rows: continue
                    extract_nl2_grid(expanded, pl_rows, period_cols, extract.data)
                    found = True
                    break
    except Exception as e:
        logger.error(f"parse_acko_nl2 failed: {e}")

    # Apply derivations
    _derive_other_income(extract.data)
    _derive_other_expenses(extract.data)
    _derive_provision_taxation(extract.data)

    return extract
