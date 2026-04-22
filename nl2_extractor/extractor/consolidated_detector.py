"""
consolidated_detector.py

Finds the page range of the NL-2 form within a consolidated PDF.

Detection strategy:
  START: First page where >= min_matches NL-2 keywords appear
  END:   Page before the next form header appears, or last page of PDF
"""

import re
import logging
import tempfile
import os
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "FORM NL-2",
    "NL-2-B-PL",
    "PROFIT AND LOSS ACCOUNT",
    "PROFIT/(LOSS) BEFORE TAX",
    "PROVISION FOR TAXATION",
    "INCOME FROM INVESTMENTS",
]

FORM_HEADER_PATTERN = re.compile(
    r"^\s*(?:FORM\s+)?NL[-\s]?(\d+)|\bFORM\s+NL[-\s]?(\d+)", 
    re.IGNORECASE | re.MULTILINE
)
def is_toc_page(text: str) -> bool:
    if re.search(r"TABLE\s+OF\s+CONTENTS|FORM\s+INDEX|INDEX\s+OF\s+FORMS", text, re.IGNORECASE):
        return True
    return False


def _page_keyword_count(text: str, keywords: List[str]) -> int:
    text_upper = text.upper()
    return sum(1 for kw in keywords if kw.upper() in text_upper)


def find_nl2_pages(
    pdf_path: str,
    keywords: Optional[List[str]] = None,
    min_matches: int = 3,
) -> Optional[Tuple[int, int]]:
    """
    Scan the consolidated PDF and return (start_page, end_page) 0-indexed
    for the NL-2 section. Returns None if NL-2 section not found.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("pdfplumber not available")
        return None

    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    try:
        with pdfplumber.open(pdf_path) as pdf:
            n_pages = len(pdf.pages)
            page_texts = []
            for page in pdf.pages:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                page_texts.append(text)

        start_page = None
        for i, text in enumerate(page_texts):
            if is_toc_page(text):
                logger.debug(f"  page {i + 1}: TOC page, skipping")
                continue
            if _page_keyword_count(text, keywords) >= min_matches:
                start_page = i
                break

        if start_page is None:
            logger.warning(f"NL-2 section not found in: {pdf_path}")
            return None

        end_page = n_pages - 1
        for i in range(start_page + 1, n_pages):
            text = page_texts[i]
            matches = FORM_HEADER_PATTERN.findall(text)
            flat_matches = []
            for m in matches:
                flat_matches.extend(g for g in m if g)
            non_nl2 = [m for m in flat_matches if m != "2"]
            if non_nl2:
                end_page = i - 1
                break

        logger.info(
            f"NL-2 found at pages {start_page}-{end_page} "
            f"(0-indexed) in {os.path.basename(pdf_path)}"
        )
        return (start_page, end_page)

    except Exception as e:
        logger.error(f"Error scanning consolidated PDF {pdf_path}: {e}")
        return None


def extract_nl2_to_temp(
    pdf_path: str,
    start_page: int,
    end_page: int,
) -> Optional[str]:
    """
    Extract pages start_page..end_page into a temporary PDF file.
    Returns the temp file path, or None on failure.
    Caller is responsible for deleting the temp file.
    """
    try:
        import pypdf
    except ImportError:
        try:
            import PyPDF2 as pypdf
        except ImportError:
            logger.error("pypdf or PyPDF2 not available")
            return None

    try:
        reader = pypdf.PdfReader(pdf_path)
        writer = pypdf.PdfWriter()
        for page_num in range(start_page, end_page + 1):
            if page_num < len(reader.pages):
                writer.add_page(reader.pages[page_num])

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="nl2_extract_")
        with open(tmp.name, "wb") as f:
            writer.write(f)

        logger.debug(f"Extracted pages {start_page}-{end_page} to {tmp.name}")
        return tmp.name

    except Exception as e:
        logger.error(f"Error extracting pages from {pdf_path}: {e}")
        return None
