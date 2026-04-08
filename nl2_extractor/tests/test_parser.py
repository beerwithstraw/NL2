"""
test_parser.py -- NL-2 parser routing and integration tests.
"""

import os
import pytest
from extractor.parser import parse_pdf
from extractor.models import NL2Extract, NL2Data

_BAJAJ_PDF = "/Users/pulkit/Desktop/Forms/FY2026/Q3/NL2/NL2_BajajGeneral.pdf"


def test_parse_pdf_bajaj_live():
    """Live extraction from the Bajaj NL2 PDF."""
    if not os.path.exists(_BAJAJ_PDF):
        pytest.skip("Bajaj NL2 PDF not found")
    extract = parse_pdf(_BAJAJ_PDF, "bajaj_allianz", "Q3", "202526")
    assert isinstance(extract, NL2Extract)
    assert extract.company_key == "bajaj_allianz"
    assert extract.form_type == "NL2"
    assert len(extract.data.data) > 0


def test_parse_pdf_bajaj_has_key_rows():
    if not os.path.exists(_BAJAJ_PDF):
        pytest.skip("Bajaj NL2 PDF not found")
    extract = parse_pdf(_BAJAJ_PDF, "bajaj_allianz", "Q3", "202526")
    data = extract.data.data
    assert "total_a" in data, "total_a must be extracted"
    assert "total_b" in data, "total_b must be extracted"
    assert "profit_before_tax" in data, "profit_before_tax must be extracted"
    assert "profit_after_tax" in data, "profit_after_tax must be extracted"


def test_parse_pdf_bajaj_pbt_equals_total_a_minus_b():
    """PBT = Total(A) - Total(B) must hold to within 3.0."""
    if not os.path.exists(_BAJAJ_PDF):
        pytest.skip("Bajaj NL2 PDF not found")
    extract = parse_pdf(_BAJAJ_PDF, "bajaj_allianz", "Q3", "202526")
    data = extract.data.data

    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        ta = data.get("total_a", {}).get(period)
        tb = data.get("total_b", {}).get(period)
        pbt = data.get("profit_before_tax", {}).get(period)
        if ta is None or tb is None or pbt is None:
            continue
        delta = abs(pbt - (ta - tb))
        assert delta <= 3.0, (
            f"PBT identity failed for {period}: "
            f"PBT={pbt}, Total(A)={ta}, Total(B)={tb}, delta={delta}"
        )


def test_parse_pdf_bajaj_pat_equals_pbt_minus_tax():
    """PAT = PBT - Tax must hold to within 3.0."""
    if not os.path.exists(_BAJAJ_PDF):
        pytest.skip("Bajaj NL2 PDF not found")
    extract = parse_pdf(_BAJAJ_PDF, "bajaj_allianz", "Q3", "202526")
    data = extract.data.data

    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        pbt = data.get("profit_before_tax", {}).get(period)
        tax = data.get("provision_taxation", {}).get(period)
        pat = data.get("profit_after_tax", {}).get(period)
        if pbt is None or pat is None:
            continue
        tax_eff = tax if tax is not None else 0.0
        delta = abs(pat - (pbt - tax_eff))
        assert delta <= 3.0, (
            f"PAT identity failed for {period}: "
            f"PAT={pat}, PBT={pbt}, Tax={tax_eff}, delta={delta}"
        )


def test_parse_pdf_no_dedicated_parser_returns_empty():
    """Companies without a dedicated parser get an empty extract with an error."""
    # Use a non-existent company key that has no dedicated parser
    extract = parse_pdf(_BAJAJ_PDF if os.path.exists(_BAJAJ_PDF) else __file__,
                        "unknown_company_xyz", "Q3", "202526")
    assert isinstance(extract, NL2Extract)
    assert len(extract.data.data) == 0
    assert len(extract.extraction_errors) > 0


def test_parse_pdf_routes_to_dedicated_parser(monkeypatch):
    """parse_pdf must route bajaj_allianz to parse_bajaj_nl2."""
    called = {}

    def fake_parser(_pdf_path, company_key, quarter, year):
        called["company_key"] = company_key
        return NL2Extract(
            source_file="fake.pdf", company_key=company_key,  # noqa: B023
            company_name="Bajaj", form_type="NL2",
            quarter=quarter, year=year, data=NL2Data(),
        )

    from extractor.companies import PARSER_REGISTRY
    monkeypatch.setitem(PARSER_REGISTRY, "parse_bajaj_nl2", fake_parser)

    parse_pdf("fake.pdf", "bajaj_allianz", "Q3", "202526")
    assert called.get("company_key") == "bajaj_allianz"
