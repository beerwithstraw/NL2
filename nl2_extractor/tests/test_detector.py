"""
test_detector.py — NL-2 form/company detection tests.
"""

import pytest
from extractor.detector import detect_all, detect_company
import os


def test_detect_all_bajaj():
    pdf_path = "/Users/pulkit/Desktop/Forms/FY2026/Q3/NL2/NL2_BajajGeneral.pdf"
    if os.path.exists(pdf_path):
        form, company, quarter, year = detect_all(pdf_path)
        assert form == "NL2"
        assert company == "bajaj_allianz"
    else:
        pytest.skip("Bajaj NL2 PDF not found at expected path")


def test_filename_detection_nl2():
    """Filenames containing NL2/NL-2/NL_2 should detect as NL2 via filename pattern."""
    from extractor.detector import _FILENAME_NL2_PATTERN
    assert _FILENAME_NL2_PATTERN.search("NL2_BajajGeneral.pdf")
    assert _FILENAME_NL2_PATTERN.search("NL-2_Q3_202526_Bajaj.pdf")
    assert _FILENAME_NL2_PATTERN.search("NL_2_2025_26_Q3_BajajGeneral.pdf")
    assert not _FILENAME_NL2_PATTERN.search("NL_06_2025_26_Q3_BajajGeneral.pdf")
    assert not _FILENAME_NL2_PATTERN.search("NL20_something.pdf")


def test_detect_company_bajaj():
    result = detect_company("NL2_BajajGeneral.pdf")
    assert result == "bajaj_allianz"


def test_detect_national_insurance():
    result = detect_company("NL2_Q3_202526_NationalInsurance.pdf")
    assert result == "national_insurance"


def test_detect_new_india():
    result = detect_company("NL2_Q3_202526_NewIndia.pdf")
    assert result == "new_india"
