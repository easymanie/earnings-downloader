"""PDF content-based quarter verification.

After downloading a PDF, reads the first 3 pages and searches for explicit
quarter mentions like 'Q2 FY26'. If found, this overrides the heuristic
quarter label assigned during scraping (which is based on release dates).
"""

import re
from collections import Counter
from typing import Optional, Tuple, Union

import fitz  # PyMuPDF

from core.models import EarningsCall

# Matches: Q1 FY26, Q3FY2026, Q2 FY 26, Q4 FY'26, etc.
QUARTER_PATTERN = re.compile(
    r'\bQ([1-4])\s*(?:FY\s*)?[\'"]?(\d{2,4})\b',
    re.IGNORECASE
)

MAX_PAGES = 3


def extract_quarter_from_pdf(
    pdf_source: Union[str, bytes],
    max_pages: int = MAX_PAGES,
) -> Optional[Tuple[str, str]]:
    """
    Extract the most likely quarter label from a PDF's first pages.

    Args:
        pdf_source: File path (str) or raw PDF bytes.
        max_pages: Number of pages to read from the start.

    Returns:
        (quarter, year) tuple like ("Q2", "FY26"), or None if not found.
    """
    try:
        if isinstance(pdf_source, bytes):
            doc = fitz.open(stream=pdf_source, filetype="pdf")
        else:
            doc = fitz.open(pdf_source)
    except Exception:
        return None

    try:
        text_parts = []
        pages_to_read = min(max_pages, len(doc))
        for i in range(pages_to_read):
            text_parts.append(doc[i].get_text())
        combined_text = "\n".join(text_parts)
    finally:
        doc.close()

    if not combined_text.strip():
        return None

    matches = QUARTER_PATTERN.findall(combined_text)
    if not matches:
        return None

    normalized = []
    for q_num, year_str in matches:
        quarter = f"Q{q_num}"
        if len(year_str) == 4:
            year = f"FY{int(year_str) % 100:02d}"
        else:
            year = f"FY{year_str}"
        normalized.append((quarter, year))

    counter = Counter(normalized)
    return counter.most_common(1)[0][0]


def verify_and_correct(
    call: EarningsCall,
    pdf_source: Union[str, bytes],
) -> Tuple[EarningsCall, bool, bool]:
    """
    Verify an EarningsCall's quarter against the PDF content.

    Returns:
        (possibly_corrected_call, was_corrected, was_verified) tuple.
        was_verified is True only if an explicit quarter was found in the PDF.
    """
    detected = extract_quarter_from_pdf(pdf_source)
    if detected is None:
        print(
            f"  Unverified: {call.company} {call.quarter} {call.year} "
            f"({call.doc_type}) — no quarter found in PDF"
        )
        return call, False, False

    detected_quarter, detected_year = detected

    if detected_quarter == call.quarter and detected_year == call.year:
        return call, False, True

    print(
        f"  Quarter corrected: {call.company} "
        f"{call.quarter} {call.year} -> {detected_quarter} {detected_year} "
        f"(from PDF content)"
    )
    corrected = call.model_copy(update={"quarter": detected_quarter, "year": detected_year})
    return corrected, True, True
