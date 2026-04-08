"""
Row Matcher logic.

Source: approach document Section 9 (Row Matcher)
"""

import logging
from typing import Dict, List, Optional

from config.row_registry import ROW_ALIASES
from extractor.normaliser import normalise_text

logger = logging.getLogger(__name__)


def build_row_map(table: List[List[str]], label_col: Optional[int] = None) -> Dict[str, int]:
    """
    Map logical rows to physical row indices.
    If label_col is None, auto-detects by scanning columns 0-2 for ROW_ALIASES matches.

    Returns
    -------
    Dict[str, int]
        Mapping of row_key (e.g. "gross_direct_premium") to row_index in the table.
    """
    row_map = {}
    if not table:
        return row_map

    # Auto-detect label column if not specified
    if label_col is None:
        best_col = 0
        max_matches = -1
        # Scan first 3 columns and top 25 rows
        for col_idx in range(min(3, len(table[0]) if table else 0)):
            matches = 0
            for row in table[:25]:
                if col_idx < len(row):
                    norm = normalise_text(str(row[col_idx]))
                    if _find_best_row_match(norm):
                        matches += 1
            if matches > max_matches:
                max_matches = matches
                best_col = col_idx
        label_col = best_col
        logger.debug(f"Auto-detected label_col: {label_col}")

    for i, row in enumerate(table):
        if not row or label_col >= len(row):
            continue

        # Target specified column (usually 0) 'Particulars'
        cell_text = str(row[label_col]) if row[label_col] is not None else ""
        norm_text = normalise_text(cell_text)

        # Standard fuzzy matching
        matched_key = _find_best_row_match(norm_text)
        
        if matched_key:
            if matched_key not in row_map:
                row_map[matched_key] = i
            else:
                logger.debug(f"Duplicate row match for {matched_key} at index {i}. Keeping first instance at {row_map[matched_key]}.")

    return row_map


def _find_best_row_match(norm_text: str) -> Optional[str]:
    """
    Find the best matching row key from ROW_ALIASES.
    Prioritizes exact matches, then substring matches.
    """
    if not norm_text:
        return None
        
    # 1. Exact match
    if norm_text in ROW_ALIASES:
        return ROW_ALIASES[norm_text]
        
    # 2. Substring match (longest alias first to avoid 'premium' matching 'gross direct premium')
    sorted_aliases = sorted(ROW_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if alias in norm_text:
            return ROW_ALIASES[alias]
            
    return None
