"""
test_heuristics.py -- NL-2 section-aware P&L row detection tests.

Tests detect_pl_rows() in _base_nl2.py:
  - Section transitions update state without assigning a key
  - "(c) Others" in provisions section -> prov_others
  - "(iii) Others" in expenses section -> exp_contribution_others
  - "(g) Others" in expenses section   -> exp_others
  - NL2_SKIP_PATTERNS rows are always skipped
  - Labels in col 1 (col 0 = serial number)
"""

import pytest
from extractor.companies._base_nl2 import detect_pl_rows


def _make_table(rows):
    """Each element: (col0, col1). Returns a 7-col table matching NL-2 layout."""
    table = []
    for col0, col1 in rows:
        table.append([col0, col1, "", "100", "200", "90", "180"])
    return table


# ---------------------------------------------------------------------------
# Basic section detection
# ---------------------------------------------------------------------------

def test_operating_section():
    table = _make_table([
        ("1", "OPERATING PROFIT/(LOSS)"),          # section header -> skip
        ("", "(a) Fire Insurance"),
        ("", "(b) Marine Insurance"),
        ("", "(c) Miscellaneous Insurance"),
    ])
    result = detect_pl_rows(table)
    assert result[1] == "op_fire"
    assert result[2] == "op_marine"
    assert result[3] == "op_miscellaneous"
    assert 0 not in result  # section header skipped


def test_investments_section():
    table = _make_table([
        ("2", "INCOME FROM INVESTMENTS"),           # section header -> skip
        ("", "(a) Interest, Dividend & Rent - Gross"),
        ("", "(b) Profit on sale of investments"),
        ("", "(c) Loss on sale/ redemption of investments"),
        ("", "(d) Amortization of Premium / Discount on Investments"),
    ])
    result = detect_pl_rows(table)
    assert result[1] == "inv_interest_dividend_rent"
    assert result[2] == "inv_profit_on_sale"
    assert result[3] == "inv_loss_on_sale"
    assert result[4] == "inv_amortization"
    assert 0 not in result


def test_total_a_detected():
    table = _make_table([
        ("", "TOTAL (A)"),
    ])
    result = detect_pl_rows(table)
    assert result[0] == "total_a"


# ---------------------------------------------------------------------------
# "(c) Others" disambiguation -- THE CRITICAL TEST
# ---------------------------------------------------------------------------

def test_c_others_in_provisions_maps_to_prov_others():
    """In the provisions section, '(c) Others' must map to prov_others."""
    table = _make_table([
        ("4", "PROVISIONS (Other than taxation)"),   # -> section = provisions
        ("", "(a) For diminution in the value of investments"),
        ("", "(b) For doubtful debts"),
        ("", "(c) Others"),                           # MUST be prov_others
    ])
    result = detect_pl_rows(table)
    assert result[3] == "prov_others", f"Expected prov_others, got {result.get(3)}"
    assert result[1] == "prov_diminution"
    assert result[2] == "prov_doubtful_debts"


def test_iii_others_in_expenses_maps_to_exp_contribution_others():
    """In the expenses section, '(iii) Others' must map to exp_contribution_others."""
    table = _make_table([
        ("5", "OTHER EXPENSES"),                      # -> section = expenses
        ("", "(f) Contribution to Policyholders' A/c"),
        ("", "(i) Towards Excess Expenses of Management"),
        ("", "(ii) Remuneration of MD/CEO/WTD/Other KMP's"),
        ("", "(iii) Others"),                          # MUST be exp_contribution_others
    ])
    result = detect_pl_rows(table)
    assert result[4] == "exp_contribution_others", f"Expected exp_contribution_others, got {result.get(4)}"


def test_g_others_in_expenses_maps_to_exp_others():
    """In the expenses section, '(g) Others' must map to exp_others."""
    table = _make_table([
        ("5", "OTHER EXPENSES"),
        ("", "(a) Expenses other than those related to Insurance Business"),
        ("", "(g) Others"),                            # MUST be exp_others
    ])
    result = detect_pl_rows(table)
    assert result[2] == "exp_others", f"Expected exp_others, got {result.get(2)}"


def test_c_others_not_in_expenses_section():
    """'(c) Others' appearing in the expenses section (unusual) should be skipped."""
    table = _make_table([
        ("5", "OTHER EXPENSES"),
        ("", "(c) Others"),    # (c) is not a known expenses alias -- should be skipped
    ])
    result = detect_pl_rows(table)
    assert 1 not in result


# ---------------------------------------------------------------------------
# Skip patterns
# ---------------------------------------------------------------------------

def test_section_header_rows_not_assigned():
    table = _make_table([
        ("4", "PROVISIONS (Other than taxation)"),
        ("5", "OTHER EXPENSES"),
        ("9", "APPROPRIATIONS"),
    ])
    result = detect_pl_rows(table)
    assert len(result) == 0, f"Section headers should not be assigned: {result}"


def test_form_title_skipped():
    table = _make_table([
        ("", "FORM NL-2-B-PL Bajaj General..."),
        ("", "PROFIT AND LOSS ACCOUNT"),
        ("", "Particulars"),
    ])
    result = detect_pl_rows(table)
    assert len(result) == 0


def test_bare_serial_number_skipped():
    table = _make_table([
        ("1", ""),    # empty col 1, serial in col 0
    ])
    result = detect_pl_rows(table)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Labels in col 1 (col 0 = serial number)
# ---------------------------------------------------------------------------

def test_labels_read_from_col1_not_col0():
    """detect_pl_rows must read from col 1, not col 0."""
    table = [
        ["1", "OPERATING PROFIT/(LOSS)", "", "", "", "", ""],
        ["", "(a) Fire Insurance", "", "100", "200", "90", "180"],
    ]
    result = detect_pl_rows(table)
    assert result[1] == "op_fire"


def test_col1_blank_falls_back_to_col0():
    """If col 1 is blank, fall back to col 0 for the label."""
    table = [
        ["TOTAL (A)", "", "", "100", "200", "90", "180"],
    ]
    result = detect_pl_rows(table)
    assert result[0] == "total_a"


# ---------------------------------------------------------------------------
# End-to-end section sequence (mirrors Bajaj PDF structure)
# ---------------------------------------------------------------------------

def test_full_bajaj_section_sequence():
    """Simulate the full Bajaj NL-2 P&L table structure."""
    table = _make_table([
        ("1", "OPERATING PROFIT/(LOSS)"),
        ("", "(a) Fire Insurance"),
        ("", "(b) Marine Insurance"),
        ("", "(c) Miscellaneous Insurance"),
        ("2", "INCOME FROM INVESTMENTS"),
        ("", "(a) Interest, Dividend & Rent - Gross"),
        ("", "(b) Profit on sale of investments"),
        ("3", "OTHER INCOME - Miscellaneous Income"),
        ("", "TOTAL (A)"),
        ("4", "PROVISIONS (Other than taxation)"),
        ("", "(a) For diminution in the value of investments"),
        ("", "(b) For doubtful debts"),
        ("", "(c) Others"),                  # prov_others
        ("5", "OTHER EXPENSES"),
        ("", "(a) Expenses other than those related to Insurance Business"),
        ("", "(g) Others"),                  # exp_others
        ("", "TOTAL (B)"),
        ("6", "Profit/(Loss) Before Tax"),
        ("7", "Provision for Taxation"),
        ("8", "Profit / (Loss) after tax"),
        ("9", "APPROPRIATIONS"),
        ("", "(a) Interim dividends paid during the year"),
        ("", "Balance carried forward to Balance Sheet"),
    ])
    result = detect_pl_rows(table)

    assert result[1] == "op_fire"
    assert result[2] == "op_marine"
    assert result[3] == "op_miscellaneous"
    assert result[5] == "inv_interest_dividend_rent"
    assert result[6] == "inv_profit_on_sale"
    assert result[7] == "other_income"
    assert result[8] == "total_a"
    assert result[10] == "prov_diminution"
    assert result[11] == "prov_doubtful_debts"
    assert result[12] == "prov_others"          # KEY: disambiguated correctly
    assert result[14] == "exp_non_insurance"
    assert result[15] == "exp_others"           # KEY: disambiguated correctly
    assert result[16] == "total_b"
    assert result[17] == "profit_before_tax"
    assert result[18] == "provision_taxation"
    assert result[19] == "profit_after_tax"
    assert result[21] == "approp_interim_dividend"
    assert result[22] == "balance_carried_forward"

    # Section headers must NOT be in result
    for section_row in (0, 4, 9, 13, 20):
        assert section_row not in result, f"Section header row {section_row} should not be in result"
