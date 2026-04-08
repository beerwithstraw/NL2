"""
Manifest generation for NL-2 PDFs.
"""

import csv
import logging
from pathlib import Path
from typing import Union

from extractor.detector import detect_all, compute_confidence
from output.organiser import get_proposed_name

logger = logging.getLogger(__name__)

MANIFEST_COLUMNS = [
    "filename",
    "detected_form",
    "detected_company",
    "detected_quarter",
    "detected_year",
    "confidence",
    "proposed_name",
    "action",
]


def generate_manifest(input_dir: Union[str, Path], output_csv: Union[str, Path]):
    input_path = Path(input_dir)
    output_path = Path(output_csv)

    if not input_path.exists() or not input_path.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(input_path.glob("*.pdf"))
    logger.info(f"Found {len(pdfs)} PDFs in {input_path}")

    rows = []
    for pdf in pdfs:
        form, company, quarter, year = detect_all(pdf)
        confidence = compute_confidence(form, company, quarter, year)
        proposed_name = (
            get_proposed_name(company, quarter, year)
            if confidence in ("HIGH", "MEDIUM") and company
            else "-"
        )
        action = "uncategorised" if (form != "NL2" or confidence == "UNKNOWN") else "proceed"
        rows.append({
            "filename": pdf.name,
            "detected_form": str(form) if form else "-",
            "detected_company": str(company) if company else "unknown",
            "detected_quarter": str(quarter) if quarter else "-",
            "detected_year": str(year) if year else "-",
            "confidence": confidence,
            "proposed_name": proposed_name,
            "action": action,
        })

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Manifest written to {output_path} with {len(rows)} entries")
    return len(rows)


def read_manifest(manifest_csv: Union[str, Path]) -> list:
    csv_path = Path(manifest_csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {csv_path}")
    valid_rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("action", "").lower() != "skip":
                valid_rows.append(row)
    return valid_rows
