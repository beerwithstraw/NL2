"""
NL-2 Parser entry point.

Routes to dedicated parsers (per company_registry.DEDICATED_PARSER) or
raises an error for companies without a dedicated parser yet.
"""

import logging
from pathlib import Path

from config.company_registry import DEDICATED_PARSER, COMPANY_DISPLAY_NAMES
from extractor.models import NL2Extract, NL2Data

logger = logging.getLogger(__name__)


def parse_pdf(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> NL2Extract:
    """
    Parse a single NL-2 PDF.

    Routing:
      1. Look up company_key in DEDICATED_PARSER.
      2. If a dedicated function name exists, look it up in PARSER_REGISTRY and call it.
      3. If no dedicated parser exists, return an empty NL2Extract with an error note.
         (NL2 has no generic parser -- every company needs a dedicated one.)
    """
    company_name = COMPANY_DISPLAY_NAMES.get(company_key, company_key.replace("_", " ").title())

    dedicated_func_name = DEDICATED_PARSER.get(company_key)
    if dedicated_func_name:
        from extractor.companies import PARSER_REGISTRY
        dedicated_func = PARSER_REGISTRY.get(dedicated_func_name)
        if dedicated_func:
            logger.info(f"Routing to dedicated parser: {dedicated_func_name}")
            return dedicated_func(pdf_path, company_key, quarter, year)
        else:
            logger.error(
                f"Dedicated parser '{dedicated_func_name}' not found in PARSER_REGISTRY "
                f"for company '{company_key}'"
            )

    # No dedicated parser available
    logger.warning(f"No dedicated NL2 parser for '{company_key}' -- returning empty extract")
    return NL2Extract(
        source_file=Path(pdf_path).name,
        company_key=company_key,
        company_name=company_name,
        form_type="NL2",
        quarter=quarter,
        year=year,
        data=NL2Data(),
        extraction_errors=[f"No dedicated NL2 parser for company '{company_key}'"],
    )
