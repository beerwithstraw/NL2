"""
NL-2 Parser entry point.

Routes to dedicated parsers (per company_registry.DEDICATED_PARSER) or
falls back to the generic header-driven NL2 parser if no dedicated parser
is registered.
"""

import logging
from pathlib import Path

from config.company_registry import DEDICATED_PARSER, COMPANY_DISPLAY_NAMES
from extractor.models import NL2Extract, NL2Data
from extractor.companies._base_nl2 import parse_header_driven_nl2

logger = logging.getLogger(__name__)


def parse_pdf(pdf_path: str, company_key: str, quarter: str = "", year: str = "") -> NL2Extract:
    """
    Parse a single NL-2 PDF.

    Routing:
      1. Look up company_key in DEDICATED_PARSER.
      2. If a dedicated function name exists, look it up in PARSER_REGISTRY and call it.
      3. If no dedicated parser exists, fall back to the generic header-driven
         NL2 parser (parse_header_driven_nl2).
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

    # Fall back to generic header-driven parser
    logger.info(f"Routing to generic NL2 parser for company: {company_key}")
    return parse_header_driven_nl2(
        pdf_path=pdf_path,
        company_key=company_key,
        company_name_fallback=company_name,
        quarter=quarter,
        year=year,
    )
