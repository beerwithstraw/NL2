"""
test_validation.py -- NL-2 identity check tests.

Checks:
  1. TOTAL_A_IDENTITY
  2. TOTAL_B_IDENTITY
  3. PBT_IDENTITY      -- PBT = Total(A) - Total(B)  [most important]
  4. PAT_IDENTITY      -- PAT = PBT - Tax
  5. YTD_GE_QTR
  6. COMPLETENESS_NL2
"""

import os
from extractor.models import NL2Extract, NL2Data
from validation.checks import (
    _check_total_a_identity,
    _check_other_expenses,
    _check_pbt_identity,
    _check_pat_identity,
    _check_ytd_ge_qtr,
    _check_completeness_nl2,
    run_validations,
    ValidationResult,
    write_validation_report,
)


def _exc(quarter="Q3", year="202526"):
    return NL2Extract(
        source_file="test.pdf",
        company_key="bajaj_allianz",
        company_name="Bajaj Allianz General Insurance Company Limited",
        form_type="NL2",
        quarter=quarter,
        year=year,
        data=NL2Data(),
    )


def _set(exc, pl_key, **periods):
    """Set period values for a pl_key. e.g. _set(exc, 'total_a', cy_ytd=100.0)"""
    exc.data.data.setdefault(pl_key, {}).update(periods)


# ---------------------------------------------------------------------------
# Total(A) Identity
# ---------------------------------------------------------------------------

def test_total_a_identity_pass():
    exc = _exc()
    _set(exc, "op_fire",                    cy_ytd=28290.0)
    _set(exc, "op_marine",                  cy_ytd=374.0)
    _set(exc, "op_miscellaneous",           cy_ytd=114383.0)
    _set(exc, "inv_interest_dividend_rent", cy_ytd=43641.0)
    _set(exc, "inv_profit_on_sale",         cy_ytd=33823.0)
    _set(exc, "inv_loss_on_sale",           cy_ytd=-2082.0)
    _set(exc, "inv_amortization",           cy_ytd=-116.0)
    _set(exc, "other_income",               cy_ytd=1.0)
    # Sum = 28290+374+114383+43641+33823-2082-116+1 = 218314
    _set(exc, "total_a",                    cy_ytd=218314.0)
    results = _check_total_a_identity(exc)
    assert any(r.period == "cy_ytd" and r.status == "PASS" for r in results)


def test_total_a_identity_fail():
    exc = _exc()
    _set(exc, "op_fire",      cy_ytd=100.0)
    _set(exc, "total_a",      cy_ytd=999.0)   # wrong
    results = _check_total_a_identity(exc)
    assert any(r.period == "cy_ytd" and r.status == "FAIL" for r in results)


def test_total_a_identity_skips_when_total_a_missing():
    exc = _exc()
    _set(exc, "op_fire", cy_ytd=100.0)
    results = _check_total_a_identity(exc)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Total(B) Identity
# ---------------------------------------------------------------------------

def test_other_expenses_derivation_pass():
    exc = _exc()
    _set(exc, "other_expenses",      cy_ytd=6972.0)
    _set(exc, "total_b",             cy_ytd=6972.0)
    results = _check_other_expenses(exc)
    assert any(r.period == "cy_ytd" and r.status == "PASS" for r in results)


# ---------------------------------------------------------------------------
# PBT Identity -- PBT = Total(A) - Total(B)
# ---------------------------------------------------------------------------

def test_pbt_identity_pass():
    exc = _exc()
    _set(exc, "total_a",          cy_ytd=218314.0, cy_qtr=55749.0)
    _set(exc, "total_b",          cy_ytd=6972.0,   cy_qtr=2701.0)
    _set(exc, "profit_before_tax",cy_ytd=211342.0, cy_qtr=53048.0)
    results = _check_pbt_identity(exc)
    pass_results = [r for r in results if r.status == "PASS"]
    assert len(pass_results) == 2, f"Expected 2 PASS results, got {[(r.period, r.status, r.delta) for r in results]}"


def test_pbt_identity_fail():
    exc = _exc()
    _set(exc, "total_a",          cy_ytd=218314.0)
    _set(exc, "total_b",          cy_ytd=6972.0)
    _set(exc, "profit_before_tax",cy_ytd=100000.0)  # wrong
    results = _check_pbt_identity(exc)
    assert any(r.status == "FAIL" for r in results)


def test_pbt_identity_skips_when_any_missing():
    exc = _exc()
    _set(exc, "total_a", cy_ytd=218314.0)
    # total_b and profit_before_tax missing
    results = _check_pbt_identity(exc)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# PAT Identity -- PAT = PBT - Tax
# ---------------------------------------------------------------------------

def test_pat_identity_pass():
    exc = _exc()
    _set(exc, "profit_before_tax", cy_ytd=211342.0, cy_qtr=53048.0)
    _set(exc, "provision_taxation",cy_ytd=53726.0,  cy_qtr=13139.0)
    _set(exc, "profit_after_tax",  cy_ytd=157616.0, cy_qtr=39909.0)
    results = _check_pat_identity(exc)
    pass_results = [r for r in results if r.status == "PASS"]
    assert len(pass_results) == 2


def test_pat_identity_no_tax_treats_as_zero():
    """If provision_taxation is missing, PAT should equal PBT."""
    exc = _exc()
    _set(exc, "profit_before_tax", cy_ytd=100.0)
    _set(exc, "profit_after_tax",  cy_ytd=100.0)
    results = _check_pat_identity(exc)
    assert any(r.status == "PASS" for r in results)


# ---------------------------------------------------------------------------
# YTD >= Qtr
# ---------------------------------------------------------------------------

def test_ytd_ge_qtr_pass():
    exc = _exc(quarter="Q3")
    _set(exc, "total_a",          cy_qtr=55749.0, cy_ytd=218314.0)
    _set(exc, "profit_before_tax",cy_qtr=53048.0, cy_ytd=211342.0)
    _set(exc, "profit_after_tax", cy_qtr=39909.0, cy_ytd=157616.0)
    results = _check_ytd_ge_qtr(exc)
    assert all(r.status == "PASS" for r in results)


def test_ytd_ge_qtr_not_checked_for_q1():
    exc = _exc(quarter="Q1")
    _set(exc, "total_a", cy_qtr=100.0, cy_ytd=50.0)   # would fail if checked
    results = _check_ytd_ge_qtr(exc)
    assert len(results) == 0


def test_ytd_ge_qtr_skips_negative():
    exc = _exc(quarter="Q3")
    _set(exc, "total_a", cy_qtr=-100.0, cy_ytd=-200.0)  # negative -- skip
    results = _check_ytd_ge_qtr(exc)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def test_completeness_fails_when_mandatory_missing():
    exc = _exc()
    results = _check_completeness_nl2(exc)
    fail_keys = {r.pl_key for r in results if r.status == "FAIL"}
    assert "total_a" in fail_keys
    assert "profit_before_tax" in fail_keys
    assert "profit_after_tax" in fail_keys


def test_completeness_pass_when_all_mandatory_present():
    exc = _exc()
    for key in ("total_a", "total_b", "profit_before_tax", "profit_after_tax"):
        _set(exc, key, cy_ytd=100.0)
    results = _check_completeness_nl2(exc)
    fail_results = [r for r in results if r.status == "FAIL"]
    assert len(fail_results) == 0


# ---------------------------------------------------------------------------
# run_validations smoke test (Bajaj actual values)
# ---------------------------------------------------------------------------

def test_run_validations_bajaj_smoke():
    """Smoke test with real Bajaj Q3 FY2026 values from PDF."""
    exc = _exc()
    _set(exc, "op_fire",                    cy_qtr=7146.0,  cy_ytd=28290.0,  py_qtr=7404.0,  py_ytd=21959.0)
    _set(exc, "op_marine",                  cy_qtr=-228.0,  cy_ytd=374.0,    py_qtr=921.0,   py_ytd=1624.0)
    _set(exc, "op_miscellaneous",           cy_qtr=32811.0, cy_ytd=114383.0, py_qtr=32690.0, py_ytd=124932.0)
    _set(exc, "inv_interest_dividend_rent", cy_qtr=12882.0, cy_ytd=43641.0,  py_qtr=12323.0, py_ytd=37565.0)
    _set(exc, "inv_profit_on_sale",         cy_qtr=4506.0,  cy_ytd=33823.0,  py_qtr=2500.0,  py_ytd=16448.0)
    _set(exc, "inv_loss_on_sale",           cy_qtr=-1057.0, cy_ytd=-2082.0,  py_qtr=-621.0,  py_ytd=-1833.0)
    _set(exc, "inv_amortization",           cy_qtr=-311.0,  cy_ytd=-116.0,   py_qtr=287.0,   py_ytd=1202.0)
    _set(exc, "other_income",               cy_qtr=0.0,     cy_ytd=1.0,      py_qtr=12.0,    py_ytd=55.0)
    _set(exc, "total_a",                    cy_qtr=55749.0, cy_ytd=218314.0, py_qtr=55516.0, py_ytd=201952.0)
    _set(exc, "prov_doubtful_debts",        cy_qtr=-43.0,   cy_ytd=22.0,     py_qtr=-161.0,  py_ytd=-91.0)
    _set(exc, "exp_non_insurance",          cy_qtr=913.0,   cy_ytd=1092.0,   py_qtr=74.0,    py_ytd=203.0)
    _set(exc, "exp_bad_debts",              cy_qtr=11.0,    cy_ytd=23.0,     py_qtr=10.0,    py_ytd=-19.0)
    _set(exc, "exp_csr",                    cy_qtr=1050.0,  cy_ytd=3246.0,   py_qtr=1345.0,  py_ytd=3241.0)
    _set(exc, "exp_remuneration_kmp",       cy_qtr=770.0,   cy_ytd=2589.0,   py_qtr=877.0,   py_ytd=2306.0)
    _set(exc, "total_b",                    cy_qtr=2701.0,  cy_ytd=6972.0,   py_qtr=2145.0,  py_ytd=5640.0)
    _set(exc, "profit_before_tax",          cy_qtr=53048.0, cy_ytd=211342.0, py_qtr=53371.0, py_ytd=196312.0)
    _set(exc, "provision_taxation",         cy_qtr=13139.0, cy_ytd=53726.0,  py_qtr=13413.0, py_ytd=49360.0)
    _set(exc, "profit_after_tax",           cy_qtr=39909.0, cy_ytd=157616.0, py_qtr=39958.0, py_ytd=146952.0)

    results = run_validations([exc])
    pass_results = [r for r in results if r.status == "PASS"]

    # Core identity checks must all pass
    pbt_results = [r for r in results if r.check_name == "PBT_IDENTITY"]
    assert all(r.status == "PASS" for r in pbt_results), \
        f"PBT_IDENTITY failures: {[(r.period, r.delta) for r in pbt_results if r.status != 'PASS']}"

    pat_results = [r for r in results if r.check_name == "PAT_IDENTITY"]
    assert all(r.status == "PASS" for r in pat_results), \
        f"PAT_IDENTITY failures: {[(r.period, r.delta) for r in pat_results if r.status != 'PASS']}"

    assert len(pass_results) > 0


# ---------------------------------------------------------------------------
# write_validation_report
# ---------------------------------------------------------------------------

def test_write_validation_report(tmp_path):
    res = [ValidationResult("Bajaj", "Q3", "202526", "total_a", "cy_ytd",
                            "PBT_IDENTITY", "PASS", 218314.0, 218314.0, 0.0, "")]
    output = tmp_path / "report.csv"
    write_validation_report(res, str(output))
    assert os.path.exists(output)
