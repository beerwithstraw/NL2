"""
File Organiser for NL-2 -- sorts input PDFs into a structured hierarchy.
"""

import shutil
import logging
from pathlib import Path
from typing import Optional

from extractor.detector import detect_all, compute_confidence
from config.settings import DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR, company_key_to_pascal

logger = logging.getLogger(__name__)


def get_proposed_name(company_key: Optional[str], quarter: Optional[str], year: Optional[str]) -> str:
    clean_company = company_key_to_pascal(company_key) if company_key else "Unknown"
    q_str = str(quarter) if quarter else "Qx"
    y_str = str(year) if year else "xxxxxx"
    return f"NL2_{q_str}_{y_str}_{clean_company}.pdf"


def organise_all(input_dir: str = DEFAULT_INPUT_DIR, output_root: str = DEFAULT_OUTPUT_DIR):
    input_path = Path(input_dir)
    output_path = Path(output_root)

    if not input_path.exists():
        logger.error(f"Input directory not found: {input_path}")
        return

    pdfs = list(input_path.glob("*.pdf"))
    logger.info(f"Found {len(pdfs)} PDFs in {input_path}")
    stats = {"NL2": 0, "uncategorised": 0, "errors": 0}

    for pdf in pdfs:
        form_type, company_key, quarter, year = detect_all(pdf)
        confidence = compute_confidence(form_type, company_key, quarter, year)

        if form_type != "NL2":
            dest_dir = output_path / "uncategorised"
            dest_name = pdf.name
            stats["uncategorised"] += 1
            reason = f"Form type detected as {form_type}, not NL2."
        elif confidence == "UNKNOWN" or not (company_key and quarter and year):
            dest_dir = output_path / "errors"
            dest_name = pdf.name
            stats["errors"] += 1
            missing = []
            if not company_key: missing.append("Company")
            if not quarter: missing.append("Quarter")
            if not year: missing.append("Year")
            reason = f"Confidence: {confidence}. Missing: {', '.join(missing)}"
        else:
            dest_dir = output_path / "NL2" / str(year) / str(quarter) / company_key
            dest_name = get_proposed_name(company_key, quarter, year)
            stats["NL2"] += 1
            reason = None

        dest_dir.mkdir(parents=True, exist_ok=True)
        final_dest = dest_dir / dest_name
        try:
            shutil.copy2(pdf, final_dest)
            if reason:
                error_file = final_dest.parent / (final_dest.stem + "_error.txt")
                with open(error_file, "w", encoding="utf-8") as f:
                    f.write(f"Detection Error for {pdf.name}\nReason: {reason}\n")
        except Exception as e:
            logger.error(f"Failed to copy {pdf.name}: {e}")

    logger.info(f"Organising complete. {stats}")
