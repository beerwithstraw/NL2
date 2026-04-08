"""
Generic table collection logic for NL-2.

Thin wrapper around pdfplumber that returns raw table rows.
The parser (via _base_nl2.py) does the structural interpretation.
"""

import pdfplumber
import logging
from typing import List

from config.settings import COLLECTOR_SNAP_TOLERANCE_LINES

logger = logging.getLogger(__name__)


def collect_tables(pdf_path: str, extraction_strategy: str = "lines") -> list:
    """
    Returns list of table objects from NL-2 pages, each with page metadata.

    Each item:
    {
        "page": int,           # 1-based page number
        "table_index": int,    # index within page (0, 1, 2...)
        "rows": list[list[str]]
    }
    """
    settings = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
        "snap_x_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
        "snap_y_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
        "intersection_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
        "join_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
        "join_x_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
        "join_y_tolerance": COLLECTOR_SNAP_TOLERANCE_LINES,
    }

    if extraction_strategy == "text":
        settings["vertical_strategy"] = "text"
        settings["horizontal_strategy"] = "lines"

    try:
        table_data = []
        with pdfplumber.open(pdf_path) as pdf:
            from extractor.companies._base_nl2 import get_nl2_pages
            for i, page in enumerate(get_nl2_pages(pdf)):
                logger.debug(f"Extracting table from page {i+1} using {extraction_strategy} strategy")
                tables = page.extract_tables(table_settings=settings)

                if not tables:
                    logger.debug(f"No tables found on page {i+1}")
                    continue

                for t_idx, table in enumerate(tables):
                    cleaned_table = []
                    for row in table:
                        cleaned_row = [
                            str(cell).strip() if cell is not None else ""
                            for cell in row
                        ]
                        if any(cell for cell in cleaned_row):
                            cleaned_table.append(cleaned_row)

                    if cleaned_table and max(len(r) for r in cleaned_table) >= 3:
                        table_data.append({
                            "page": i + 1,
                            "table_index": t_idx,
                            "rows": cleaned_table
                        })

        if not table_data:
            logger.warning(f"No tables extracted from {pdf_path}")

        return table_data

    except Exception as e:
        logger.error(f"Table extraction failed for {pdf_path}: {e}")
        return []
