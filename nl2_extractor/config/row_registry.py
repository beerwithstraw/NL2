"""
Row (P&L line item) Master Registry for NL-2-B-PL Profit and Loss Account.

All row labels in NL-2 forms are normalised to canonical keys.
Every company-specific label maps to one of these keys via NL2_ROW_ALIASES.

Source: NL-2-B-PL form structure (IRDAI).
Section-awareness note: "(c) Others" (provisions) vs "(g) Others" (expenses)
must be disambiguated by section context in detect_pl_rows(), not here.
"""

import re

# Canonical row keys — ordered for output.
# 32 entries — the fixed row structure for all NL-2 forms.
NL2_ROW_ORDER = [
    # --- Section 1: Operating Profit/Loss (from NL-1) ---
    "op_fire",
    "op_marine",
    "op_miscellaneous",
    # --- Section 2: Income from Investments ---
    "inv_interest_dividend_rent",
    "inv_profit_on_sale",
    "inv_loss_on_sale",
    "inv_amortization",
    # --- Section 3: Other Income ---
    "other_income",
    # --- Summary ---
    "total_a",
    # --- Section 4: Provisions (Other than taxation) ---
    "prov_diminution",
    "prov_doubtful_debts",
    "prov_others",
    # --- Section 5: Other Expenses ---
    "exp_non_insurance",
    "exp_bad_debts",
    "exp_subordinated_debt",
    "exp_csr",
    "exp_penalties",
    "exp_contribution_policyholders",
    "exp_excess_management",
    "exp_remuneration_kmp",
    "exp_contribution_others",
    "exp_others",
    "exp_investment_writeoff",
    # --- Summary ---
    "total_b",
    # --- Bottom line items ---
    "profit_before_tax",
    "provision_taxation",
    "profit_after_tax",
    # --- Appropriations ---
    "approp_interim_dividend",
    "approp_final_dividend",
    "approp_transfer_reserves",
    "balance_brought_forward",
    "balance_carried_forward",
]

# Display-friendly names (exact canonical PDF labels)
NL2_ROW_DISPLAY_NAMES = {
    "op_fire":                           "(a) Fire Insurance",
    "op_marine":                         "(b) Marine Insurance",
    "op_miscellaneous":                  "(c) Miscellaneous Insurance",
    "inv_interest_dividend_rent":        "(a) Interest, Dividend & Rent \u2013 Gross",
    "inv_profit_on_sale":                "(b) Profit on sale of investments",
    "inv_loss_on_sale":                  "(c) Loss on sale/ redemption of investments",
    "inv_amortization":                  "(d) Amortization of Premium / Discount on Investments",
    "other_income":                      "Other Income - Miscellaneous Income",
    "total_a":                           "TOTAL (A)",
    "prov_diminution":                   "(a) For diminution in the value of investments",
    "prov_doubtful_debts":               "(b) For doubtful debts",
    "prov_others":                       "(c) Others [Provisions]",
    "exp_non_insurance":                 "(a) Expenses other than those related to Insurance Business",
    "exp_bad_debts":                     "(b) Bad debts written off",
    "exp_subordinated_debt":             "(c) Interest on subordinated debt",
    "exp_csr":                           "(d) Expenses towards CSR activities",
    "exp_penalties":                     "(e) Penalties",
    "exp_contribution_policyholders":    "(f) Contribution to Policyholders' A/c",
    "exp_excess_management":             "(i) Towards Excess Expenses of Management",
    "exp_remuneration_kmp":              "(ii) Remuneration of MD/CEO/WTD/Other KMP's",
    "exp_contribution_others":           "(iii) Others [Contribution sub-items]",
    "exp_others":                        "(g) Others",
    "exp_investment_writeoff":           "(i) Investment written off",
    "total_b":                           "TOTAL (B)",
    "profit_before_tax":                 "Profit/(Loss) Before Tax",
    "provision_taxation":                "Provision for Taxation",
    "profit_after_tax":                  "Profit / (Loss) after tax",
    "approp_interim_dividend":           "(a) Interim dividends paid during the year",
    "approp_final_dividend":             "(b) Final dividend paid",
    "approp_transfer_reserves":          "(c) Transfer to any Reserves or Other Accounts",
    "balance_brought_forward":           "Balance of profit/ loss brought forward from last year",
    "balance_carried_forward":           "Balance carried forward to Balance Sheet",
}

# Hierarchy depth: 0 = summary, 1 = line item, 2 = sub-item
NL2_ROW_DEPTH = {
    "op_fire":                          1,
    "op_marine":                        1,
    "op_miscellaneous":                 1,
    "inv_interest_dividend_rent":       1,
    "inv_profit_on_sale":               1,
    "inv_loss_on_sale":                 1,
    "inv_amortization":                 1,
    "other_income":                     1,
    "total_a":                          0,
    "prov_diminution":                  1,
    "prov_doubtful_debts":              1,
    "prov_others":                      1,
    "exp_non_insurance":                1,
    "exp_bad_debts":                    1,
    "exp_subordinated_debt":            1,
    "exp_csr":                          1,
    "exp_penalties":                    1,
    "exp_contribution_policyholders":   1,
    "exp_excess_management":            2,
    "exp_remuneration_kmp":             2,
    "exp_contribution_others":          2,
    "exp_others":                       1,
    "exp_investment_writeoff":          2,
    "total_b":                          0,
    "profit_before_tax":                0,
    "provision_taxation":               0,
    "profit_after_tax":                 0,
    "approp_interim_dividend":          1,
    "approp_final_dividend":            1,
    "approp_transfer_reserves":         1,
    "balance_brought_forward":          0,
    "balance_carried_forward":          0,
}

# Observed PDF row labels -> canonical key.
# IMPORTANT: "(c) others" and "(iii) others" are section-context-dependent.
# detect_pl_rows() in _base_nl2.py uses the section state to disambiguate.
# These ambiguous keys are NOT in this dict — they are handled in detect_pl_rows().
NL2_ROW_ALIASES = {
    # op_fire
    "(a) fire insurance":                                       "op_fire",
    "fire insurance":                                           "op_fire",
    "(a) fire":                                                 "op_fire",

    # op_marine
    "(b) marine insurance":                                     "op_marine",
    "marine insurance":                                         "op_marine",
    "(b) marine":                                               "op_marine",

    # op_miscellaneous
    "(c) miscellaneous insurance":                              "op_miscellaneous",
    "miscellaneous insurance":                                  "op_miscellaneous",
    "(c) miscellaneous":                                        "op_miscellaneous",

    # inv_interest_dividend_rent
    "(a) interest, dividend & rent - gross":                    "inv_interest_dividend_rent",
    "(a) interest, dividend & rent \u2013 gross":              "inv_interest_dividend_rent",
    "(a) interest, dividend & rent gross":                      "inv_interest_dividend_rent",
    "interest, dividend & rent - gross":                        "inv_interest_dividend_rent",
    "interest, dividend & rent \u2013 gross":                  "inv_interest_dividend_rent",
    "interest dividend & rent gross":                           "inv_interest_dividend_rent",
    "(a) interest dividend and rent gross":                     "inv_interest_dividend_rent",

    # inv_profit_on_sale
    "(b) profit on sale of investments":                        "inv_profit_on_sale",
    "profit on sale of investments":                            "inv_profit_on_sale",

    # inv_loss_on_sale
    "(c) loss on sale/ redemption of investments":              "inv_loss_on_sale",
    "(c) loss on sale/redemption of investments":               "inv_loss_on_sale",
    "loss on sale/ redemption of investments":                  "inv_loss_on_sale",
    "loss on sale/redemption of investments":                   "inv_loss_on_sale",
    "loss on sale of investments":                              "inv_loss_on_sale",

    # inv_amortization
    "(d) amortization of premium / discount on investments":    "inv_amortization",
    "(d) amortisation of premium / discount on investments":    "inv_amortization",
    "(d) amortization of premium/ discount on investments":     "inv_amortization",
    "amortization of premium / discount on investments":        "inv_amortization",
    "amortisation of premium / discount on investments":        "inv_amortization",
    "amortization of premium":                                  "inv_amortization",

    # other_income
    "other income - miscellaneous income":                      "other_income",
    "other income \u2013 miscellaneous income":                "other_income",
    "other income":                                             "other_income",
    "miscellaneous income":                                     "other_income",

    # total_a
    "total (a)":                                                "total_a",

    # prov_diminution
    "(a) for diminution in the value of investments":           "prov_diminution",
    "for diminution in the value of investments":               "prov_diminution",

    # prov_doubtful_debts
    "(b) for doubtful debts":                                   "prov_doubtful_debts",
    "for doubtful debts":                                       "prov_doubtful_debts",

    # NOTE: "(c) others" (prov_others) is OMITTED — section-aware in detect_pl_rows()

    # exp_non_insurance
    "(a) expenses other than those related to insurance business":  "exp_non_insurance",
    "expenses other than those related to insurance business":      "exp_non_insurance",

    # exp_bad_debts
    "(b) bad debts written off":                                "exp_bad_debts",
    "bad debts written off":                                    "exp_bad_debts",

    # exp_subordinated_debt — NOTE: uses "(c)" but is in EXPENSES section, not provisions
    # detect_pl_rows() handles this correctly because state is "expenses" here
    "(c) interest on subordinated debt":                        "exp_subordinated_debt",
    "interest on subordinated debt":                            "exp_subordinated_debt",

    # exp_csr
    "(d) expenses towards csr activities":                      "exp_csr",
    "expenses towards csr activities":                          "exp_csr",

    # exp_penalties
    "(e) penalties":                                            "exp_penalties",
    "penalties":                                                "exp_penalties",

    # exp_contribution_policyholders
    "(f) contribution to policyholders' a/c":                   "exp_contribution_policyholders",
    "(f) contribution to policyholders\u2019 a/c":             "exp_contribution_policyholders",
    "contribution to policyholders' a/c":                       "exp_contribution_policyholders",

    # exp_excess_management
    "(i) towards excess expenses of management":                "exp_excess_management",
    "towards excess expenses of management":                    "exp_excess_management",

    # exp_remuneration_kmp
    "(ii) remuneration of md/ceo/wtd/other kmp's":              "exp_remuneration_kmp",
    "(ii) remuneration of md/ceo/wtd/other kmp\u2019s":        "exp_remuneration_kmp",
    "remuneration of md/ceo/wtd/other kmp":                     "exp_remuneration_kmp",
    "remuneration of md/ceo/wtd/other kmp's":                   "exp_remuneration_kmp",

    # NOTE: "(iii) others" (exp_contribution_others) is OMITTED — section-aware
    # NOTE: "(g) others" (exp_others) is OMITTED — section-aware

    # exp_investment_writeoff
    "(i) investment written off":                               "exp_investment_writeoff",
    "investment written off":                                   "exp_investment_writeoff",

    # total_b
    "total (b)":                                                "total_b",

    # profit_before_tax
    "profit/(loss) before tax":                                 "profit_before_tax",
    "profit / (loss) before tax":                               "profit_before_tax",
    "profit before tax":                                        "profit_before_tax",
    "profit/loss before tax":                                   "profit_before_tax",

    # provision_taxation
    "provision for taxation":                                   "provision_taxation",

    # profit_after_tax
    "profit / (loss) after tax":                                "profit_after_tax",
    "profit/(loss) after tax":                                  "profit_after_tax",
    "profit after tax":                                         "profit_after_tax",

    # approp_interim_dividend
    "(a) interim dividends paid during the year":               "approp_interim_dividend",
    "interim dividends paid during the year":                   "approp_interim_dividend",

    # approp_final_dividend
    "(b) final dividend paid":                                  "approp_final_dividend",
    "final dividend paid":                                      "approp_final_dividend",

    # approp_transfer_reserves
    "(c) transfer to any reserves or other accounts (to be specified)": "approp_transfer_reserves",
    "(c) transfer to any reserves or other accounts":           "approp_transfer_reserves",
    "transfer to any reserves or other accounts":               "approp_transfer_reserves",

    # balance_brought_forward
    "balance of profit/ loss brought forward from last year":   "balance_brought_forward",
    "balance of profit/loss brought forward from last year":    "balance_brought_forward",
    "balance of profit/ loss brought forward":                  "balance_brought_forward",
    "balance of profit/loss brought forward":                   "balance_brought_forward",

    # balance_carried_forward
    "balance carried forward to balance sheet":                 "balance_carried_forward",
    "balance carried forward":                                  "balance_carried_forward",
}

# Rows to skip — section header rows and column header rows.
# Compiled as patterns matched against normalised (lowercase, stripped) label text.
NL2_SKIP_PATTERNS = [
    re.compile(r"^operating profit"),           # section header
    re.compile(r"^income from investments$"),   # section header
    re.compile(r"^provisions \(other"),         # section header
    re.compile(r"^other expenses$"),            # section header
    re.compile(r"^appropriations$"),            # section header
    re.compile(r"^sources of funds"),           # wrong form
    re.compile(r"^schedule ref"),               # column header row
    re.compile(r"^particulars$"),               # column header row
    re.compile(r"^form nl"),                    # form title row
    re.compile(r"^profit and loss"),            # form title row
    re.compile(r"^\d+$"),                       # bare serial numbers
]
