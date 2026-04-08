"""
LOB (Line of Business) Master Registry.

All LOBs are normalised to canonical keys. Every company-specific header
string maps to one of these keys via LOB_ALIASES.

Source: approach document Section 5.1
Anti-hallucination rule #4: aliases are ONLY from observed PDF headers.
"""

# Canonical LOB keys — ordered for output (verification sheets & Master_Data).
# This is the single source of truth for LOB column ordering.
# 24 entries covering all onboarded companies.
LOB_ORDER = [
    "fire",
    "marine_cargo",
    "marine_hull",
    "total_marine",
    "motor_od",
    "motor_tp",
    "total_motor",
    "health",
    "personal_accident",
    "travel_insurance",
    "total_health",
    "wc_el",                        # Workmen's Compensation / Employer's Liability
    "public_product_liability",
    "engineering",
    "aviation",
    "crop_insurance",
    "credit_insurance",             # Bajaj Allianz only (Phase 1)
    "other_liability",              # HDFC Ergo only (Phase 1)
    "specialty",                    # HDFC Ergo only (Phase 1)
    "home",                         # HDFC Ergo only (Phase 1)
    "other_segments",               # PSU insurers
    "other_miscellaneous",
    "total_miscellaneous",
    "grand_total",
]

# Display-friendly names for each canonical LOB key.
LOB_DISPLAY_NAMES = {
    "fire": "Fire",
    "marine_cargo": "Marine Cargo",
    "marine_hull": "Marine Hull",
    "total_marine": "Total Marine",
    "motor_od": "Motor OD",
    "motor_tp": "Motor TP",
    "total_motor": "Total Motor",
    "health": "Health",
    "personal_accident": "Personal Accident",
    "travel_insurance": "Travel Insurance",
    "total_health": "Total Health",
    "wc_el": "WC / EL",
    "public_product_liability": "Public / Product Liability",
    "engineering": "Engineering",
    "aviation": "Aviation",
    "crop_insurance": "Crop Insurance",
    "credit_insurance": "Credit Insurance",
    "other_liability": "Other Liability",
    "specialty": "Specialty",
    "home": "Home",
    "other_segments": "Other Segments",
    "other_miscellaneous": "Other Miscellaneous",
    "total_miscellaneous": "Total Miscellaneous",
    "grand_total": "Grand Total",
}

# Maps every observed PDF header string (lowercased) → canonical LOB key.
# Only strings actually observed in onboarded company PDFs are included.
LOB_ALIASES = {
    # --- Fire ---
    "fire": "fire",

    # --- Marine ---
    "marine cargo": "marine_cargo",
    "marine hull": "marine_hull",
    "total marine": "total_marine",

    # --- Motor ---
    "motor od": "motor_od",
    "miscellaneous motor od": "motor_od",
    "miscelaneous motor od": "motor_od",
    "motor ownerdamage": "motor_od",
    "motor tp": "motor_tp",
    "motor thirdparty": "motor_tp",
    "or tp": "motor_tp",
    "total motor": "total_motor",
    "motor": "total_motor",

    # --- Health ---
    "health": "health",
    "personal accident": "personal_accident",
    "travel insurance": "travel_insurance",
    "travel": "travel_insurance",
    "total health": "total_health",
    "total health segment": "total_health",
    "health segment": "total_health",
    "total health / total miscellaneous": "total_health",
    "total health/total miscellaneous": "total_health",

    # --- Miscellaneous individual LOBs ---
    "workmen\u2019s compensation/ employer\u2019s liability": "wc_el",   # curly apostrophe
    "workmen's compensation/ employer's liability": "wc_el",          # straight apostrophe
    "workmen's compensation/": "wc_el",                               # truncated header
    "workmen\u2019s compensation": "wc_el",                           # HDFC Ergo
    "workmen's compensation": "wc_el",                                # generic abbreviation
    "wc/el": "wc_el",
    "public/ product liability": "public_product_liability",
    "public/product liability": "public_product_liability",
    "engineering": "engineering",
    "aviation": "aviation",
    "crop insurance": "crop_insurance",
    "weather / crop insurance": "crop_insurance",                     # HDFC Ergo
    "weather/crop insurance": "crop_insurance",                       # HDFC Ergo alt
    "weather and crop insurance": "crop_insurance",                   # Reliance General

    # --- Company-specific LOBs ---
    "credit insurance": "credit_insurance",                           # Bajaj Allianz
    "other liability": "other_liability",                             # HDFC Ergo
    "specialty": "specialty",                                         # HDFC Ergo
    "home": "home",                                                   # HDFC Ergo

    # --- Segments / Totals ---
    "other segments": "other_segments",
    "other segments (b)": "other_segments",                           # PSU variant
    "other miscellaneous segment": "other_miscellaneous",
    "other miscellaneous": "other_miscellaneous",
    "other misc.": "other_miscellaneous",
    "total miscellaneous": "total_miscellaneous",
    "grand total": "grand_total",
    "grand total segment": "grand_total",

    # --- Typos observed in PDFs ---
    "miscelaneous": "total_miscellaneous",                            # Bajaj Allianz typo
}

# ---------------------------------------------------------------------------
# Company-Specific LOB Aliases
# ---------------------------------------------------------------------------
COMPANY_SPECIFIC_ALIASES = {
    "care_health": {
        "total": "grand_total"
    },
    "star_health": {
        "miscellaneous health": "health",
        "total health / total miscellaneous": "total_health",
        "grand total": "grand_total"
    },
    "future_generali": {
        "health insurance":     "health",
        "others":               "other_miscellaneous",
        "liability":            "public_product_liability",
        "workmen compensation": "wc_el",
    },
    "shriram_general": {
        "total": "grand_total",
    },
    "universal_sompo": {
        "trade credit": "credit_insurance",
    },
    "iffco_tokio": {
        "motor-od":                         "motor_od",
        "motor-tp":                         "motor_tp",
        "motor-total":                      "total_motor",
        "workmen compensation":             "wc_el",
        "public/product liability":         "public_product_liability",
        "health (excl travel)":             "health",
        "total health (incl pa & travel)":  "total_health",
        "crop":                             "crop_insurance",
        "other miscellaneous":              "other_miscellaneous",
        "total miscellaneous":              "total_miscellaneous",
    },
    "magma_general": {
        "travel":  "travel_insurance",
        "crop":    "crop_insurance",
        "others":  "other_miscellaneous",
    },
    "sbi_general": {
        "motor (od)":               "motor_od",
        "motor (tp)":               "motor_tp",
        "motor total":              "total_motor",
        "workmen's compensation":   "wc_el",
        "public liability":         "public_product_liability",
        "health insurance":         "health",
        "weather & crop insurance": "crop_insurance",
        "others":                   "other_miscellaneous",
        "miscellaneous*":           "total_miscellaneous",
        "total":                    "grand_total",
    },
}

# Companies that only do Health (Standalone Health Insurers) 
# which should ignore Fire/Marine/Motor in COMPLETENESS checks
COMPLETENESS_IGNORE = {
    "care_health": ["fire", "marine_cargo", "marine_hull", "total_marine", "motor_od", "motor_tp", "total_motor", "total_health", "wc_el", "public_product_liability", "engineering", "aviation", "crop_insurance", "other_miscellaneous", "total_miscellaneous"],
    "manipal_cigna": ["fire", "marine_cargo", "marine_hull", "total_marine", "motor_od", "motor_tp", "total_motor", "total_health", "wc_el", "public_product_liability", "engineering", "aviation", "crop_insurance", "other_miscellaneous", "total_miscellaneous"],
    "niva_bupa": ["fire", "marine_cargo", "marine_hull", "total_marine", "motor_od", "motor_tp", "total_motor", "total_health", "wc_el", "public_product_liability", "engineering", "aviation", "crop_insurance", "other_miscellaneous", "total_miscellaneous"],
    "star_health": ["fire", "marine_cargo", "marine_hull", "total_marine", "motor_od", "motor_tp", "total_motor", "total_health", "wc_el", "public_product_liability", "engineering", "aviation", "crop_insurance", "other_miscellaneous", "total_miscellaneous"],
    "future_generali": ["credit_insurance", "other_segments", "aviation"],
    "shriram_general": ["health", "personal_accident", "travel_insurance", "total_health", "wc_el", "public_product_liability", "engineering", "aviation", "crop_insurance", "credit_insurance", "other_liability", "specialty", "home", "other_segments", "other_miscellaneous", "marine_hull"],
    "zurich_kotak":    ["aviation", "crop_insurance", "marine_hull", "travel_insurance"],
    "zuno":            ["aviation", "crop_insurance", "marine_hull", "public_product_liability"],
    "aic":             ["fire", "marine_cargo", "marine_hull", "total_marine",
                        "motor_od", "motor_tp", "total_motor", "health",
                        "personal_accident", "travel_insurance", "total_health",
                        "wc_el", "public_product_liability", "engineering",
                        "aviation", "other_segments"],
    "narayana_health": ["fire", "marine_cargo", "marine_hull", "total_marine",
                        "motor_od", "motor_tp", "total_motor", "total_health",
                        "personal_accident", "travel_insurance",
                        "wc_el", "public_product_liability", "engineering",
                        "aviation", "crop_insurance", "other_segments",
                        "other_miscellaneous"],
    "navi_general":    ["fire", "marine_cargo", "marine_hull", "total_marine",
                        "motor_od", "crop_insurance",
                        "other_segments", "aviation",
                        "other_miscellaneous", "public_product_liability",
                        "travel_insurance", "wc_el"],
    "national_insurance": ["other_segments", "travel_insurance"],
    "new_india":       ["travel_insurance"],
    "raheja_qbe":      ["travel_insurance", "aviation", "crop_insurance",
                        "marine_hull", "other_segments"],
    "universal_sompo": ["aviation"],
    "aditya_birla_health": [
        "fire", "marine_cargo", "marine_hull", "total_marine",
        "motor_od", "motor_tp", "total_motor",
        "wc_el", "public_product_liability", "engineering", "aviation",
        "crop_insurance", "credit_insurance", "other_liability", "specialty",
        "home", "other_segments", "other_miscellaneous", "total_miscellaneous",
        "grand_total"],
    "ecgc": [
        "fire", "marine_cargo", "marine_hull", "total_marine",
        "motor_od", "motor_tp", "total_motor",
        "health", "personal_accident", "travel_insurance", "total_health",
        "wc_el", "public_product_liability", "engineering", "aviation",
        "crop_insurance", "other_liability", "specialty",
        "home", "other_segments", "other_miscellaneous", "total_miscellaneous",
        "grand_total"],
    "acko": ["fire", "marine_cargo", "marine_hull", "total_marine",
             "wc_el", "engineering", "aviation", "crop_insurance",
             "credit_insurance", "other_liability", "specialty",
             "home", "other_segments"],
    "chola_ms":        ["aviation", "crop_insurance"],
    "go_digit":        ["aviation", "marine_hull"],
    "oriental_insurance": ["other_segments"],
    "iffco_tokio":     ["marine_hull", "other_segments", "aviation"],
    "liberty_general": ["aviation", "crop_insurance", "marine_hull", "other_segments"],
    "magma_general":   ["other_segments", "aviation", "crop_insurance", "marine_hull",
                        "travel_insurance"],
    "royal_sundaram":  ["aviation", "crop_insurance", "marine_hull"],
    "sbi_general":     ["marine_hull", "other_segments", "aviation", "total_marine"],
    "united_india":    ["other_segments", "other_miscellaneous", "travel_insurance"],
    "indusind_general": ["other_segments"],
    "kshema_general":  ["fire", "marine_cargo", "marine_hull", "total_marine",
                        "motor_od", "motor_tp", "total_motor",
                        "health", "travel_insurance",
                        "wc_el", "public_product_liability", "engineering",
                        "aviation", "other_segments", "other_miscellaneous"],
}
