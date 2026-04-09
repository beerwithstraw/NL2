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
    "section_operating",          # display-only header; depth=-1; no data extracted
    "op_fire",
    "op_marine",
    "op_miscellaneous",
    # --- Section 2: Income from Investments ---
    "section_investments",        # display-only header
    "inv_interest_dividend_rent",
    "inv_profit_on_sale",
    "inv_loss_on_sale",
    "inv_amortization",
    # --- Section 3: Other Income ---
    "other_income",
    # --- Summary ---
    "total_a",
    # --- Section 4: Provisions (Other than taxation) ---
    "section_provisions",         # display-only header
    "prov_diminution",
    "prov_doubtful_debts",
    "prov_others",
    # --- Section 5: Other Expenses (reverse-calculated: total_b - provisions) ---
    "section_expenses",           # display-only header
    "other_expenses",             # = total_b - prov_diminution - prov_doubtful_debts - prov_others
    # --- Summary ---
    "total_b",
    # --- Bottom line items ---
    "profit_before_tax",
    "provision_taxation",
    "profit_after_tax",
    # --- Appropriations ---
    "section_appropriations",     # display-only header
    "approp_interim_dividend",
    "approp_final_dividend",
    "approp_transfer_reserves",
    "balance_brought_forward",
    "balance_carried_forward",
]

# Display-friendly names (exact canonical PDF labels)
NL2_ROW_DISPLAY_NAMES = {
    # Section headers (depth=-1) — display only
    "section_operating":                 "Operating Profit / (Loss)",
    "section_investments":               "Income from Investments",
    "section_provisions":                "Provisions (Other than Taxation)",
    "section_expenses":                  "Other Expenses",
    "section_appropriations":            "Appropriations",
    # Data rows
    "op_fire":                           "(a) Fire Insurance",
    "op_marine":                         "(b) Marine Insurance",
    "op_miscellaneous":                  "(c) Miscellaneous Insurance",
    "inv_interest_dividend_rent":        "(a) Interest, Dividend & Rent \u2013 Gross",
    "inv_profit_on_sale":                "(b) Profit on sale of investments",
    "inv_loss_on_sale":                  "(c) Loss on sale/ redemption of investments",
    "inv_amortization":                  "(d) Amortization of Premium / Discount on Investments",
    "other_income":                      "Other Income - Miscellaneous Income [Calculated]",
    "total_a":                           "TOTAL (A)",
    "prov_diminution":                   "(a) For diminution in the value of investments",
    "prov_doubtful_debts":               "(b) For doubtful debts",
    "prov_others":                       "(c) Others [Provisions]",
    "other_expenses":                    "Other Expenses (Total)",
    "total_b":                           "TOTAL (B)",
    "profit_before_tax":                 "Profit/(Loss) Before Tax",
    "provision_taxation":                "Provision for Taxation [Calculated]",
    "profit_after_tax":                  "Profit / (Loss) after tax",
    "approp_interim_dividend":           "(a) Interim dividends paid during the year",
    "approp_final_dividend":             "(b) Final dividend paid",
    "approp_transfer_reserves":          "(c) Transfer to any Reserves or Other Accounts",
    "balance_brought_forward":           "Balance of profit/ loss brought forward from last year",
    "balance_carried_forward":           "Balance carried forward to Balance Sheet",
}

# Hierarchy depth: -1 = section header (display only), 0 = summary, 1 = line item, 2 = sub-item
NL2_ROW_DEPTH = {
    "section_operating":                -1,
    "section_investments":              -1,
    "section_provisions":               -1,
    "section_expenses":                 -1,
    "section_appropriations":           -1,
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
    "other_expenses":                   1,
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
    "interest , dividend & rent - gross":                       "inv_interest_dividend_rent",
    "interest , dividend & rent  - gross":                      "inv_interest_dividend_rent",
    "(a) interest , dividend & rent - gross":                   "inv_interest_dividend_rent",

    # inv_profit_on_sale
    "(b) profit on sale of investments":                        "inv_profit_on_sale",
    "profit on sale of investments":                            "inv_profit_on_sale",
    "(b) profit on sale / redemption of investments":           "inv_profit_on_sale",

    # inv_loss_on_sale
    "(c) loss on sale/ redemption of investments":              "inv_loss_on_sale",
    "(c) loss on sale/redemption of investments":               "inv_loss_on_sale",
    "(c) (loss on sale/ redemption of investments)":            "inv_loss_on_sale",
    "(c) (loss on sale/redemption of investments)":             "inv_loss_on_sale",
    "(c) (loss on sale / redemption of investments)":           "inv_loss_on_sale",
    "(c) (loss) on sale/ redemption of investments":            "inv_loss_on_sale",
    "(c) (loss on sale)/ redemption of investments":            "inv_loss_on_sale",
    "loss on sale/ redemption of investments":                  "inv_loss_on_sale",
    "loss on sale/redemption of investments":                   "inv_loss_on_sale",
    "loss on sale of investments":                              "inv_loss_on_sale",
    "(c) loss on sale of investments":                          "inv_loss_on_sale",
    "(c) less: loss on sale/redemption of investments":          "inv_loss_on_sale",

    # inv_amortization
    "(d) amortization of premium / discount on investments":    "inv_amortization",
    "(d) amortisation of premium / discount on investments":    "inv_amortization",
    "(d) amortization of premium/ discount on investments":     "inv_amortization",
    "(d) amortization of premium/discount on investments":      "inv_amortization",
    "(c) amortization of premium / discount on investments":    "inv_amortization",
    "(d) less: amortization of premium/discount on investments": "inv_amortization",
    "(d) amortization of (premium) / discount on investments":   "inv_amortization",
    "(d) amortization of premium / (discount) on investments":   "inv_amortization",
    "amortization of premium / discount on investments":        "inv_amortization",
    "amortisation of premium / discount on investments":        "inv_amortization",
    "amortization of premium":                                  "inv_amortization",

    # other_income
    "profit / (loss) on sale of assets":                        "other_income",
    "recovery of bad debts written off":                        "other_income",
    "other income - miscellaneous income":                      "other_income",
    "other income \u2013 miscellaneous income":                "other_income",
    "other income":                                             "other_income",
    "(a) other income":                                         "other_income",
    "b) other income":                                          "other_income",
    "(c) others(other income)":                                "other_income",
    "other income (to be specified)":                           "other_income",
    "other income (miscellaneous receipts)":                    "other_income",
    "miscellaneous income":                                     "other_income",
    "c) miscellaneous income":                                  "other_income",
    "other income (i) profit/loss on sale of fixed assets, (ii) exchange gain/loss, (iii) old unclaimed balance written back, (iv) misc (like transfer fee, duplicate fee) (v) int on income tax refund": "other_income",
    "(a) interest on income tax refund":                        "other_income",
    "(b) interest on income tax refund":                        "other_income",
    "(a) interest income on tax refund":                        "other_income",
    "interest on income tax refund":                            "other_income",
    "other income (interest on it refund )":                    "other_income",
    "(a) bad debts recovered":                                  "other_income",
    "(a) bad debts/balances written back":                      "other_income",
    "(b) liability written back":                               "other_income",
    "(c) recovery of bad debts written off":                    "other_income",
    "(c) miscellaneous income":                                 "other_income",
    "(c ) provision written back":                              "other_income",
    "(b) provision written back":                               "other_income",

    # total_a
    "total (a)":                                                "total_a",
    "total(a)":                                                 "total_a",
    "total ( a )":                                              "total_a",
    "total (a+b)":                                              "total_a",

    # prov_diminution
    "(a) for diminution in the value of investments":           "prov_diminution",
    "for diminution in the value of investments":               "prov_diminution",
    "i) provision on standard assets/npa":                      "prov_diminution",
    "(c) others- provision for doubtful investments":           "prov_diminution",
    "(a) provision for diminution in value of investments written back": "prov_diminution",
    "(a) for diminution in the value of investments (written back)": "prov_diminution",
    "provision for diminution in the value of investments":     "prov_diminution",

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

    # total_b
    "total (b)":                                                "total_b",

    # profit_before_tax
    "profit/(loss) before tax":                                 "profit_before_tax",
    "profit / (loss) before tax":                               "profit_before_tax",
    "profit before tax":                                        "profit_before_tax",
    "profit/loss before tax":                                   "profit_before_tax",
    "profit/(loss) before tax (a-b)":                          "profit_before_tax",
    "profit before tax (a-b)":                                 "profit_before_tax",
    "profit/ (loss) before tax ( a - b)":                      "profit_before_tax",
    "profit/ (loss) before tax":                               "profit_before_tax",

    # provision_taxation — current tax + deferred tax components all accumulate
    "provision for taxation":                                   "provision_taxation",
    "current tax":                                              "provision_taxation",
    "tax":                                                      "provision_taxation",
    "provision for taxation / taxation of earlier years":       "provision_taxation",
    "(a) current tax":                                          "provision_taxation",
    "(i) current tax":                                          "provision_taxation",
    "(a) current tax /mat payable":                             "provision_taxation",
    "(a) current tax / mat payable":                            "provision_taxation",
    "(a) current tax \ minimum alternate tax":                  "provision_taxation",
    "(a) current tax / minimum alternate tax":                  "provision_taxation",
    "- current tax":                                            "provision_taxation",
    "current tax expense":                                      "provision_taxation",
    "provision for taxation - current tax":                     "provision_taxation",
    "provision for taxation (inclusive of mat)":                "provision_taxation",
    "income tax":                                               "provision_taxation",
    # deferred tax sub-items — accumulated into provision_taxation
    "(b) deferred tax":                                         "provision_taxation",
    "(b) deferred tax (income) / expense":                      "provision_taxation",
    "(b) deferred tax (income)/expense":                        "provision_taxation",
    "(c) deferred tax (income) / expense":                      "provision_taxation",
    "(c) deferred tax (income)/expense":                        "provision_taxation",
    "deferred tax for current period":                          "provision_taxation",
    "deferred tax for earlier year":                            "provision_taxation",
    "(ii) deferred tax":                                        "provision_taxation",
    "deferred tax":                                             "provision_taxation",
    "short provision for earlier year":                         "provision_taxation",
    "short/(excess) provision of earlier years":                "provision_taxation",
    "(c) short/(excess) provision of earlier years":            "provision_taxation",
    "prior period adjustments":                                 "provision_taxation",
    "(iii) tax relating to earlier years":                      "provision_taxation",
    "tax relating to earlier years":                            "provision_taxation",

    # profit_after_tax
    "profit / (loss) after tax":                                "profit_after_tax",
    "profit/(loss) after tax":                                  "profit_after_tax",
    "profit after tax":                                         "profit_after_tax",
    "profit/ (loss) after tax":                                 "profit_after_tax",

    # approp_interim_dividend
    "(a) interim dividends paid during the year":               "approp_interim_dividend",
    "(a) interim dividends paid during the period":             "approp_interim_dividend",
    "(a) interim dividends paid during the period / year":      "approp_interim_dividend",
    "interim dividends paid during the year":                   "approp_interim_dividend",
    "interim dividends paid during the period":                 "approp_interim_dividend",

    # approp_final_dividend
    "(b) final dividend paid":                                  "approp_final_dividend",
    "final dividend paid":                                      "approp_final_dividend",

    # approp_transfer_reserves
    "(c) transfer to any reserves or other accounts (to be specified)": "approp_transfer_reserves",
    "(c) transfer to any reserves or other accounts ( to be specified )": "approp_transfer_reserves",
    "(c) transfer to any reserves or other accounts":           "approp_transfer_reserves",
    "(d) transfer to any reserves or other account":           "approp_transfer_reserves",
    "(c) transfer to debenture redemption reserve":             "approp_transfer_reserves",
    "(d) transfer to debenture redemption reserve":             "approp_transfer_reserves",
    "transfer to any reserves or other accounts":               "approp_transfer_reserves",
    "(d) transfer to any reserves or other account":            "approp_transfer_reserves",
    "(d) transfer to reserves":                                 "approp_transfer_reserves",
    "transfer to reserve":                                      "approp_transfer_reserves",
    "(d) debenture redemption reserve":                         "approp_transfer_reserves",

    # balance_brought_forward
    "balance of profit/ loss brought forward from last year":   "balance_brought_forward",
    "balance of profit/loss brought forward from last year":    "balance_brought_forward",
    "balance of profit/ (loss) brought forward from last year": "balance_brought_forward",
    "balance of profit/(loss) brought forward from last year":  "balance_brought_forward",
    "balance of profit/ loss brought forward from last period": "balance_brought_forward",
    "balance of profit/ loss brought forward from period/year": "balance_brought_forward",
    "balance of profit/ loss brought forward from last year/period": "balance_brought_forward",
    "balance of profit/ (loss) brought forward from last period / year": "balance_brought_forward",
    "balance of profit / (loss) brought forward from last quarter/year": "balance_brought_forward",
    "balance of profit/ loss brought forward from last quarter/year": "balance_brought_forward",
    "balance of profit/ loss brought forward":                  "balance_brought_forward",
    "balance of profit/loss brought forward":                   "balance_brought_forward",
    "balance of profit / loss brought forward":                 "balance_brought_forward",

    # balance_carried_forward
    "balance carried forward to balance sheet":                 "balance_carried_forward",
    "balance carried forward to reserves and surplus/balance sheet": "balance_carried_forward",
    "balance carried forward":                                  "balance_carried_forward",

    # op_miscellaneous variant with extra space
    "(c ) miscellaneous insurance":                             "op_miscellaneous",
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
    re.compile(r"^periodic disclosures"),       # form title row
    re.compile(r"^\d+$"),                       # bare serial numbers
    re.compile(r"^\(amount in"),                # unit header row
    re.compile(r"^notes?:?\s+to form"),         # footnote block
    re.compile(r"^notes?:\s"),                  # footnote
    re.compile(r"^\(iii\) tax relating"),       # not a P&L item
    re.compile(r"^-tax relating"),              # not a P&L item
    re.compile(r"^\(c\) dividend distribution tax"),  # sub-item
    re.compile(r"^mat credit"),                 # sub-item
    re.compile(r"^less:"),                      # compound taxation block
    re.compile(r"^s\.?\s*no\.?$"),             # S.No column header
    re.compile(r"^\( in "),                    # unit header e.g. "( in Lakhs)"
    re.compile(r"registration no\."),          # company registration text block
    re.compile(r"^name of the insurer"),       # header label
    re.compile(r"profit and loss account for the"),  # repeated form title within cell
]
