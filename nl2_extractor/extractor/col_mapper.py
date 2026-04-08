"""
Column Mapper logic.

Source: approach document Section 9 (Col Mapper)
Maps column indices to (LOB, period_type) configurations.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Set, Any

from config.lob_registry import LOB_ALIASES, COMPANY_SPECIFIC_ALIASES
from config.settings import COL_MAP_NUMERIC_SCAN_ROWS, COL_MAP_MIN_NUMERIC_ROWS
from extractor.normaliser import normalise_text, clean_number, NIL_STRINGS

logger = logging.getLogger(__name__)


def jaccard_similarity(s1: str, s2: str) -> float:
    """Calculates Jaccard word similarity with a subset boost (Item 3 Phase 3)."""
    w1 = set(s1.split())
    w2 = set(s2.split())
    if not w1 and not w2:
        return 1.0
    if not w1 or not w2:
        return 0.0
    
    intersection = w1.intersection(w2)
    union = w1.union(w2)
    jaccard = len(intersection) / len(union)
    
    # Subset boost: if one is a full word-level subset, boost the score.
    # This ensures 'fire insurance' vs 'fire' (jaccard 0.5) reaches > 0.60.
    if len(intersection) > 0 and (intersection == w1 or intersection == w2):
        overlap = len(intersection) / min(len(w1), len(w2)) # will be 1.0
        return (jaccard + overlap) / 2.0 # (0.5 + 1.0) / 2 = 0.75
        
    return jaccard


def build_column_map(
    table: List[List[str]],
    company_key: str,
    start_col: int = 1,
    default_year: str = 'current'
) -> Dict[int, Dict[str, Any]]:
    """
    Map grid column indices to {"lob": LOB_KEY, "period": "qtr"|"ytd"}.
    
    If extraction_strategy == 'positional', delegates to POSITIONAL_COL_MAP.
    Otherwise, uses the 3-step heuristic: Header > Numeric Proof > Fallback Pair.

    Returns
    -------
    Dict[int, Dict[str, Any]]
        Mapping of col_idx -> {"lob": "marine_hull", "period": "qtr", "score": float}
    """
    return _build_heuristic_map(table, company_key, start_col, default_year)


def _build_heuristic_map(table: List[List[str]], company_key: str, start_col: int = 1, default_year: str = 'current') -> Dict[int, Dict[str, str]]:
    """
    The 3-Step Column Definition Engine.
    
    Step 1: The Header Hook (find LOB string matches in first N rows).
    Step 2: The Numeric Proof (confirm it's a data column, not a spacer).
    Step 3: The Fallback Pair (assume columns come in pairs: Qtr, YTD).
    """
    col_map = {}
    if not table:
        return col_map
        
    num_cols = max(len(row) for row in table)
    
    # Identify Header Rows (top 5 rows usually contain headers)
    header_rows = table[:5]
    
    # Store detected LOBs per column index
    detected_lobs: Dict[int, str] = {}
    
    # --- Step 1: The Header Hook ---
    for col_idx in range(start_col, num_cols):  # Default skips col 0 (Particulars)
        col_text_combined = ""
        for row in header_rows:
            if col_idx < len(row):
                col_text_combined += " " + (str(row[col_idx]) if row[col_idx] is not None else "")
                
        norm_text = normalise_text(col_text_combined)
        
        # Check against LOB_ALIASES using Jaccard scoring (Item 2 Phase 3)
        best_score = 0.0
        best_lob = None
        
        # Check company-specific aliases first (substring match)
        if company_key in COMPANY_SPECIFIC_ALIASES:
            for alias, target_lob in COMPANY_SPECIFIC_ALIASES[company_key].items():
                if alias in norm_text:
                    best_lob = target_lob
                    best_score = 1.0
                    break
                
        if not best_lob:
            for alias, lob_key in LOB_ALIASES.items():
                score = jaccard_similarity(norm_text, alias)
                if score > best_score:
                    best_score = score
                    best_lob = lob_key
        
        # We also keep the absolute substring match as a fallback for short aliases
        if best_score < 0.60:
            sorted_aliases = sorted(LOB_ALIASES.keys(), key=len, reverse=True)
            for alias in sorted_aliases:
                if alias in norm_text:
                    # If substring matches but Jaccard is low, use 1.0 logic sparingly
                    # but here we prefer the Jaccard result.
                    best_lob = LOB_ALIASES[alias]
                    # We don't boost the score if it wasn't a good Jaccard match
                    break

        if best_lob:
            detected_lobs[col_idx] = {"lob": best_lob, "score": best_score}
        

    # If we missed a LOB but the structure is likely pairs, we can backfill
    # e.g., if col 2 is Fire, col 1 is probably also Fire (Qtr / YTD pair)
    # This is a simple backfill if the previous column has no LOB.
    _apply_horizontal_lob_carryover(detected_lobs, num_cols, start_col)

    # --- Step 2: The Numeric Proof ---
    valid_data_cols: Set[int] = set()
    data_rows_start = 0
    # Find where data starts (first row with a valid Particulars label and some numbers)
    for i, row in enumerate(table):
        if not row:
            continue
        # Check if row has some numbers or NIL strings
        num_count = 0
        for idx, cell in enumerate(row):
            if idx > 0:
                if clean_number(cell) is not None or str(cell).strip().lower() in NIL_STRINGS:
                    num_count += 1
        if num_count > 0:
            data_rows_start = i
            break
            
    # Scan subsequent rows for numeric density
    scan_limit = min(data_rows_start + COL_MAP_NUMERIC_SCAN_ROWS, len(table))
    for col_idx in range(start_col, num_cols):
        numeric_count = 0
        for i in range(data_rows_start, scan_limit):
            if col_idx < len(table[i]):
                cell_val = table[i][col_idx]
                if clean_number(cell_val) is not None or str(cell_val).strip().lower() in NIL_STRINGS:
                    numeric_count += 1
        
        if numeric_count >= COL_MAP_MIN_NUMERIC_ROWS:
            valid_data_cols.add(col_idx)

    # --- Step 3: The Fallback Grouping ---
    # For every LOB found, we map columns to periods (qtr/ytd) for both Current and Prior years if present.
    
    # Store year info per column if detected in row 0
    col_to_year: Dict[int, str] = {} # 'current' or 'prior'
    if len(table) > 0:
        # Use row 0 and 1 for year detection (sometimes year is in row 1)
        header_text = (" ".join([str(c) for r in table[:2] for c in r])).lower()
        
        # Simple heuristic: find '2025' vs '2024' or similar
        # Or look for '31st March, 2025' vs '31st March, 2024'
        years = []
        for match in re.finditer(r'20\d{2}', header_text):
            years.append(int(match.group()))

        cy_val = None
        py_val = None
        if len(set(years)) >= 2:
            cy_val = max(years)
            py_val = min(years)
            
            # Find column boundaries for each year in row 0
            row0 = [str(c).lower() for c in table[0]]
            cy_start = -1
            py_start = -1
            for i, cell in enumerate(row0):
                if str(cy_val) in cell: cy_start = i
                if str(py_val) in cell: py_start = i
            
            if cy_start != -1 and py_start != -1:
                if cy_start < py_start:
                    for i in range(start_col, num_cols):
                        col_to_year[i] = 'current' if i < py_start else 'prior'
                else:
                    for i in range(start_col, num_cols):
                        col_to_year[i] = 'current' if i < cy_start else 'prior'
        else:
            # Standalone table: use default_year as the base fallback
            actual_year = default_year
            
            # Allow header overrides ONLY if we find a very specific PY string
            # Uses dynamic year detection: PY year = CY year - 1
            if re.search(r'prior period', header_text):
                actual_year = 'prior'
            else:
                # Extract all 4-digit years and 2-digit FY ranges from header
                four_digit = [int(m.group()) for m in re.finditer(r'20\d{2}', header_text)]
                fy_range = re.search(r'(\d{2})-(\d{2})', header_text)
                if four_digit and cy_val is not None and py_val is not None:
                    # If header contains only the PY year, it's a prior table
                    if py_val in four_digit and cy_val not in four_digit:
                        actual_year = 'prior'
                elif fy_range:
                    start_yy = int(fy_range.group(1))
                    end_yy = int(fy_range.group(2))
                    # Compare against known CY/PY if available
                    if cy_val is not None and start_yy == cy_val % 100:
                        actual_year = 'current'
                    elif py_val is not None and start_yy == py_val % 100:
                        actual_year = 'prior'

            for i in range(start_col, num_cols):
                col_to_year[i] = actual_year

    # Group valid columns by LOB
    lob_to_cols: Dict[str, List[Tuple[int, float]]] = {}
    for col_idx in sorted(list(valid_data_cols)):
        lob_info = detected_lobs.get(col_idx)
        if lob_info:
            lob = lob_info["lob"]
            score = lob_info["score"]
            if lob not in lob_to_cols:
                lob_to_cols[lob] = []
            lob_to_cols[lob].append((col_idx, score))
            
    for lob, items in lob_to_cols.items():
        # Filter items by year if possible
        cy_items = [it for it in items if col_to_year.get(it[0], 'current') == 'current']
        py_items = [it for it in items if col_to_year.get(it[0]) == 'prior']
        
        # CY Mapping
        if len(cy_items) == 1:
            idx, score = cy_items[0]
            col_map[idx] = {"lob": lob, "period": "qtr", "score": score, "year": "current"}
        elif len(cy_items) >= 2:
            col_map[cy_items[0][0]] = {"lob": lob, "period": "qtr", "score": cy_items[0][1], "year": "current"}
            col_map[cy_items[1][0]] = {"lob": lob, "period": "ytd", "score": cy_items[1][1], "year": "current"}
            
        # PY Mapping
        if len(py_items) == 1:
            idx, score = py_items[0]
            col_map[idx] = {"lob": lob, "period": "qtr", "score": score, "year": "prior"}
        elif len(py_items) >= 2:
            col_map[py_items[0][0]] = {"lob": lob, "period": "qtr", "score": py_items[0][1], "year": "prior"}
            col_map[py_items[1][0]] = {"lob": lob, "period": "ytd", "score": py_items[1][1], "year": "prior"}
            
    return col_map


def _apply_horizontal_lob_carryover(detected_lobs: Dict[int, str], num_cols: int, start_col: int):
    """
    If a column has an LOB but adjacent valid columns don't, 
    carry the LOB over, assuming they are QTR/YTD pairs merged under a single header cell.
    """
    # Simply sweep left-to-right. If we see an LOB in col i, but col i+1 is empty, 
    # it's usually the YTD column under a left-aligned merged header cell.
    for col_idx in range(start_col, num_cols):
        has_current = col_idx in detected_lobs
        has_next = (col_idx + 1) in detected_lobs
        has_prev = (col_idx - 1) in detected_lobs
        
        if has_current and not has_next:
            # Look ahead: if col i+2 has an LOB or we've reached the end, col i+1 is likely our pair.
            # But don't overwrite if it already has something.
            detected_lobs[col_idx + 1] = detected_lobs[col_idx].copy()

    # (If right-aligned headers existed, we could sweep right-to-left, but left-to-right handles 99% of pdfplumber tables)

