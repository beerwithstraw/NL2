"""
Data models for the NL2 Profit and Loss Account extractor.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class NL2Data:
    """
    Holds extracted P&L data for one company.

    data[pl_key]["cy_qtr" | "cy_ytd" | "py_qtr" | "py_ytd"] = float | None
    """
    data: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)


@dataclass
class NL2Extract:
    """Top-level container for one extracted NL-2 PDF."""
    source_file: str
    company_key: str                # e.g. "bajaj_allianz"
    company_name: str               # e.g. "Bajaj Allianz General Insurance..."
    form_type: str = "NL2"
    quarter: str = ""               # e.g. "Q3"
    year: str = ""                  # e.g. "202526"
    data: NL2Data = field(default_factory=NL2Data)
    extraction_warnings: list = field(default_factory=list)
    extraction_errors: list = field(default_factory=list)
