"""
P&L line item metadata — sort keys, section groupings, and hierarchy depth.

Used by excel_writer.py to populate PL_PARTICULARS and Grouped_PL columns.
"""

PL_METADATA = {
    # Section headers — depth=-1, no data rows in Master_Data
    "section_operating":                ("00-SECTION_OP",        "OPERATING PROFIT"),
    "section_investments":              ("03b-SECTION_INV",      "INVESTMENTS"),
    "section_provisions":               ("09b-SECTION_PROV",     "PROVISIONS"),
    "section_expenses":                 ("12b-SECTION_EXP",      "EXPENSES"),
    "section_appropriations":           ("27b-SECTION_APPROP",   "APPROPRIATIONS"),
    # Data rows
    "op_fire":                          ("01-OP_FIRE",           "OPERATING PROFIT"),
    "op_marine":                        ("02-OP_MARINE",         "OPERATING PROFIT"),
    "op_miscellaneous":                 ("03-OP_MISC",           "OPERATING PROFIT"),
    "inv_interest_dividend_rent":       ("04-INV_INTEREST",      "INVESTMENTS"),
    "inv_profit_on_sale":               ("05-INV_PROFIT",        "INVESTMENTS"),
    "inv_loss_on_sale":                 ("06-INV_LOSS",          "INVESTMENTS"),
    "inv_amortization":                 ("07-INV_AMORT",         "INVESTMENTS"),
    "other_income":                     ("08-OTHER_INCOME",      "OTHER INCOME"),
    "total_a":                          ("09-TOTAL_A",           "TOTALS"),
    "prov_diminution":                  ("10-PROV_DIM",          "PROVISIONS"),
    "prov_doubtful_debts":              ("11-PROV_DOUBTFUL",     "PROVISIONS"),
    "prov_others":                      ("12-PROV_OTHERS",       "PROVISIONS"),
    "other_expenses":                   ("13-OTHER_EXP",         "EXPENSES"),
    "total_b":                          ("14-TOTAL_B",           "TOTALS"),
    "profit_before_tax":                ("15-PBT",               "TOTALS"),
    "provision_taxation":               ("16-TAX",               "TOTALS"),
    "profit_after_tax":                 ("17-PAT",               "TOTALS"),
    "approp_interim_dividend":          ("18-APPROP_INTERIM",    "APPROPRIATIONS"),
    "approp_final_dividend":            ("19-APPROP_FINAL",      "APPROPRIATIONS"),
    "approp_transfer_reserves":         ("20-APPROP_TRANSFER",   "APPROPRIATIONS"),
    "balance_brought_forward":          ("21-BAL_BF",            "APPROPRIATIONS"),
    "balance_carried_forward":          ("22-BAL_CF",            "APPROPRIATIONS"),
}


def get_pl_particulars(pl_key: str) -> str:
    """Return the sort key (PL_PARTICULARS) for a canonical P&L key."""
    return PL_METADATA.get(pl_key, (pl_key, ""))[0]


def get_grouped_pl(pl_key: str) -> str:
    """Return the section grouping (Grouped_PL) for a canonical P&L key."""
    return PL_METADATA.get(pl_key, ("", pl_key))[1]
