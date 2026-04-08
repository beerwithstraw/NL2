"""
test_collector.py — NL-2 table collector tests.
"""

import pytest
from extractor.collector import collect_tables
import os

_BAJAJ_PDF = "/Users/pulkit/Desktop/Forms/FY2026/Q3/NL2/NL2_BajajGeneral.pdf"


def test_collect_tables_bajaj():
    if os.path.exists(_BAJAJ_PDF):
        tables = collect_tables(_BAJAJ_PDF)
        assert len(tables) > 0
        assert "rows" in tables[0]
        assert "page" in tables[0]
    else:
        pytest.skip("Bajaj NL2 PDF not found")


def test_collect_tables_invalid_file():
    tables = collect_tables("non_existent.pdf")
    assert tables == []


def test_collect_tables_structure():
    if os.path.exists(_BAJAJ_PDF):
        tables = collect_tables(_BAJAJ_PDF)
        for table in tables:
            for row in table["rows"]:
                assert isinstance(row, list)
                for cell in row:
                    assert cell is None or isinstance(cell, str)
    else:
        pytest.skip("Bajaj NL2 PDF not found")
