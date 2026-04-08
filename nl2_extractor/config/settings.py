"""
Global constants, tolerances, and configuration for the NL2 Extractor.
"""

# --- Versioning ---
EXTRACTOR_VERSION = "1.0.0"

# --- Tolerances ---
# Column mapper minimum Jaccard similarity score threshold
COL_MAP_MIN_SCORE = 0.30

# Column mapper: minimum numeric values in first N data rows to confirm a column
COL_MAP_MIN_NUMERIC_ROWS = 1
COL_MAP_NUMERIC_SCAN_ROWS = 10

# Collector snap/join tolerance (pixels)
COLLECTOR_SNAP_TOLERANCE_LINES = 4
COLLECTOR_SNAP_TOLERANCE_TEXT = 3

# --- Default Paths ---
DEFAULT_INPUT_DIR = "inputs"
DEFAULT_OUTPUT_DIR = "outputs"

# --- FY Year String Helper ---

def make_fy_string(start_year: int, end_year: int) -> str:
    """
    Build the 6-character FY string.
    e.g. start=2025, end=2026 -> '202526'
    """
    return f"{start_year}{end_year % 100:02d}"


QUARTER_TO_FY = {
    "Q1": lambda y: make_fy_string(y, y + 1),      # June 2025 -> 202526
    "Q2": lambda y: make_fy_string(y, y + 1),      # Sep 2024 -> 202425
    "Q3": lambda y: make_fy_string(y, y + 1),      # Dec 2024 -> 202425
    "Q4": lambda y: make_fy_string(y - 1, y),       # Mar 2025 -> 202425
}

# --- Master Sheet Column Order (fixed — do not reorder) ---
# NL2 has 4 data columns (CY_Qtr, CY_YTD, PY_Qtr, PY_YTD) plus Hierarchy_Depth.
MASTER_COLUMNS = [
    "PL_PARTICULARS",               # A
    "Grouped_PL",                   # B
    "Hierarchy_Depth",              # C
    "Company_Name",                 # D
    "Company",                      # E
    "NL",                           # F
    "Quarter",                      # G
    "Year",                         # H
    "Year_Info",                    # I
    "Quarter_Info",                 # J
    "Sector",                       # K
    "Industry_Competitors",         # L
    "GI_Companies",                 # M
    "CY_Qtr",                       # N
    "CY_YTD",                       # O
    "PY_Qtr",                       # P
    "PY_YTD",                       # Q
    "Source_File",                  # R
]

# --- Excel Formatting ---
NUMBER_FORMAT = "#,##0.00"
LOW_CONFIDENCE_FILL_COLOR = "FFFF99"
VERIFIED_FILL_COLOR = "CCFFCC"
ALTERNATING_ROW_FILL = "F2F2F2"

# --- Common Helpers ---

def company_key_to_pascal(company_key: str) -> str:
    """
    Convert snake_case company key to PascalCase for folder and filename use.
    e.g. "bajaj_allianz" -> "BajajAllianz"
         "hdfc_ergo"     -> "HdfcErgo"
    """
    return company_key.replace("_", " ").title().replace(" ", "")
