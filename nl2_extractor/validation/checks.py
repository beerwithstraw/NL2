"""
Validation Checks for NL-2-B-PL Profit and Loss Account.

Identity checks:
  1. TOTAL_A_IDENTITY       -- Total(A) = Operating Profit (fire+marine+misc) + Investments + Other Income
  2. TOTAL_B_IDENTITY       -- Total(B) = sum(Provisions) + sum(Other Expenses)
  3. PBT_IDENTITY           -- PBT = Total(A) - Total(B)
  4. PAT_IDENTITY           -- PAT = PBT - Provision for Taxation
  5. YTD_GE_QTR             -- CY_YTD >= CY_Qtr for summary rows (with sign check)
  6. COMPLETENESS_NL2       -- Mandatory rows must be non-null for cy_ytd
"""

import csv
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from extractor.models import NL2Extract

logger = logging.getLogger(__name__)

TOLERANCE = 1.0
IDENTITY_TOLERANCE = 3.0


@dataclass
class ValidationResult:
    company: str
    quarter: str
    year: str
    pl_key: str         # P&L row key (or "ALL" for completeness checks)
    period: str         # e.g. "cy_qtr", "cy_ytd", "py_qtr", "py_ytd"
    check_name: str
    status: str         # PASS, WARN, FAIL
    expected: Optional[float]
    actual: Optional[float]
    delta: Optional[float]
    note: str


def run_validations(extractions: List[NL2Extract]) -> List[ValidationResult]:
    """Run all NL-2 validation checks against the provided extractions."""
    results = []
    for exc in extractions:
        results.extend(_check_total_a_identity(exc))
        results.extend(_check_total_b_identity(exc))
        results.extend(_check_pbt_identity(exc))
        results.extend(_check_pat_identity(exc))
        results.extend(_check_ytd_ge_qtr(exc))
        results.extend(_check_completeness_nl2(exc))
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(data: NL2Extract, pl_key: str, period: str) -> Optional[float]:
    v = data.data.data.get(pl_key, {}).get(period)
    return float(v) if v is not None else None


def _make(exc, pl_key, period, check_name, status, expected, actual, delta, note=""):
    return ValidationResult(
        exc.company_name, exc.quarter, exc.year, pl_key, period,
        check_name, status, expected, actual, delta, note,
    )


# ---------------------------------------------------------------------------
# Check 1: TOTAL_A_IDENTITY
# Total(A) = op_fire + op_marine + op_miscellaneous
#            + inv_interest + inv_profit + inv_loss + inv_amort
#            + other_income
# ---------------------------------------------------------------------------

_TOTAL_A_COMPONENTS = [
    "op_fire", "op_marine", "op_miscellaneous",
    "inv_interest_dividend_rent", "inv_profit_on_sale",
    "inv_loss_on_sale", "inv_amortization",
    "other_income",
]


def _check_total_a_identity(exc: NL2Extract) -> List[ValidationResult]:
    results = []
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        total = _get(exc, "total_a", period)
        if total is None:
            continue
        component_sum = sum(
            (_get(exc, k, period) or 0.0) for k in _TOTAL_A_COMPONENTS
        )
        n_found = sum(1 for k in _TOTAL_A_COMPONENTS if _get(exc, k, period) is not None)
        if n_found == 0:
            continue
        delta = abs(total - component_sum)
        status = "PASS" if delta <= IDENTITY_TOLERANCE else "FAIL"
        results.append(_make(exc, "total_a", period, "TOTAL_A_IDENTITY", status,
                             component_sum, total, delta))
    return results


# ---------------------------------------------------------------------------
# Check 2: TOTAL_B_IDENTITY
# Total(B) = sum(Provisions) + sum(Other Expenses)
# ---------------------------------------------------------------------------

_TOTAL_B_COMPONENTS = [
    "prov_diminution", "prov_doubtful_debts", "prov_others",
    "exp_non_insurance", "exp_bad_debts", "exp_subordinated_debt",
    "exp_csr", "exp_penalties", "exp_contribution_policyholders",
    "exp_excess_management", "exp_remuneration_kmp", "exp_contribution_others",
    "exp_others", "exp_investment_writeoff",
]


def _check_total_b_identity(exc: NL2Extract) -> List[ValidationResult]:
    results = []
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        total = _get(exc, "total_b", period)
        if total is None:
            continue
        component_sum = sum(
            (_get(exc, k, period) or 0.0) for k in _TOTAL_B_COMPONENTS
        )
        n_found = sum(1 for k in _TOTAL_B_COMPONENTS if _get(exc, k, period) is not None)
        if n_found == 0:
            continue
        delta = abs(total - component_sum)
        status = "PASS" if delta <= IDENTITY_TOLERANCE else "FAIL"
        results.append(_make(exc, "total_b", period, "TOTAL_B_IDENTITY", status,
                             component_sum, total, delta))
    return results


# ---------------------------------------------------------------------------
# Check 3: PBT_IDENTITY — PBT = Total(A) - Total(B)
# ---------------------------------------------------------------------------

def _check_pbt_identity(exc: NL2Extract) -> List[ValidationResult]:
    results = []
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        pbt = _get(exc, "profit_before_tax", period)
        total_a = _get(exc, "total_a", period)
        total_b = _get(exc, "total_b", period)
        if any(v is None for v in (pbt, total_a, total_b)):
            continue
        expected = total_a - total_b
        delta = abs(pbt - expected)
        status = "PASS" if delta <= IDENTITY_TOLERANCE else "FAIL"
        results.append(_make(exc, "profit_before_tax", period, "PBT_IDENTITY", status,
                             expected, pbt, delta))
    return results


# ---------------------------------------------------------------------------
# Check 4: PAT_IDENTITY — PAT = PBT - Tax
# ---------------------------------------------------------------------------

def _check_pat_identity(exc: NL2Extract) -> List[ValidationResult]:
    results = []
    for period in ("cy_qtr", "cy_ytd", "py_qtr", "py_ytd"):
        pat = _get(exc, "profit_after_tax", period)
        pbt = _get(exc, "profit_before_tax", period)
        tax = _get(exc, "provision_taxation", period)
        if any(v is None for v in (pat, pbt)):
            continue
        tax_eff = tax if tax is not None else 0.0
        expected = pbt - tax_eff
        delta = abs(pat - expected)
        status = "PASS" if delta <= IDENTITY_TOLERANCE else "FAIL"
        results.append(_make(exc, "profit_after_tax", period, "PAT_IDENTITY", status,
                             expected, pat, delta))
    return results


# ---------------------------------------------------------------------------
# Check 5: YTD >= Qtr (for summary rows, Q2/Q3/Q4 only)
# Applied to: total_a, profit_before_tax, profit_after_tax
# Only when both values are non-negative
# ---------------------------------------------------------------------------

_YTD_GE_QTR_ROWS = ["total_a", "profit_before_tax", "profit_after_tax"]


def _check_ytd_ge_qtr(exc: NL2Extract) -> List[ValidationResult]:
    # Only meaningful for Q2, Q3, Q4
    if exc.quarter not in ("Q2", "Q3", "Q4"):
        return []
    results = []
    for pl_key in _YTD_GE_QTR_ROWS:
        ytd = _get(exc, pl_key, "cy_ytd")
        qtr = _get(exc, pl_key, "cy_qtr")
        if ytd is None or qtr is None:
            continue
        # Skip if either is negative (losses can flip the comparison)
        if ytd < 0 or qtr < 0:
            continue
        delta = ytd - qtr
        status = "PASS" if delta >= -TOLERANCE else "WARN"
        results.append(_make(exc, pl_key, "cy", "YTD_GE_QTR", status,
                             qtr, ytd, delta,
                             note="YTD should be >= Qtr for non-loss rows"))
    return results


# ---------------------------------------------------------------------------
# Check 6: COMPLETENESS — mandatory rows must be non-null for cy_ytd
# ---------------------------------------------------------------------------

_MANDATORY_ROWS = {"total_a", "total_b", "profit_before_tax", "profit_after_tax"}
_WARN_IF_MISSING = set([
    "op_fire", "op_marine", "op_miscellaneous",
    "inv_interest_dividend_rent",
    "provision_taxation",
])


def _check_completeness_nl2(exc: NL2Extract) -> List[ValidationResult]:
    results = []
    from config.row_registry import NL2_ROW_ORDER
    for pl_key in NL2_ROW_ORDER:
        val = _get(exc, pl_key, "cy_ytd")
        if val is None:
            status = "FAIL" if pl_key in _MANDATORY_ROWS else "WARN"
            results.append(_make(exc, pl_key, "cy_ytd", "COMPLETENESS_NL2", status,
                                 None, None, None,
                                 note=f"{pl_key} missing cy_ytd value"))
    return results


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def build_validation_summary_table(results: List[ValidationResult]):
    from rich.table import Table
    counts = {"PASS": 0, "SKIP": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    t = Table(title="NL2 Validation Summary")
    t.add_column("Status", style="bold")
    t.add_column("Count", justify="right")
    t.add_row("[green]PASS[/green]", str(counts["PASS"]))
    t.add_row("[blue]SKIP[/blue]", str(counts["SKIP"]))
    t.add_row("[yellow]WARN[/yellow]", str(counts["WARN"]))
    t.add_row("[red]FAIL[/red]", str(counts["FAIL"]))
    return t


def write_validation_report(results: List[ValidationResult], output_path: str):
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "company", "quarter", "year", "pl_key", "period",
            "check_name", "status", "expected", "actual", "delta", "note",
        ])
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    logger.info(f"Validation report saved to {output_path}")
