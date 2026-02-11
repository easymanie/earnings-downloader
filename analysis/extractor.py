"""PDF text extraction for earnings documents."""

import os
from typing import List, Tuple

import fitz  # PyMuPDF
import pdfplumber
from pydantic import BaseModel, Field


class ExtractedDocument(BaseModel):
    """Result of PDF text extraction."""
    file_path: str
    doc_type: str
    text: str = ""
    tables: List[dict] = Field(default_factory=list)
    page_count: int = 0
    extraction_method: str = ""
    quality_score: float = 0.0
    char_count: int = 0


class PDFExtractor:
    """Extract text from earnings PDFs with strategy selection by doc type."""

    def extract(self, file_path: str, doc_type: str) -> ExtractedDocument:
        """
        Extract text from a PDF file.

        Transcripts use PyMuPDF (fast, text-heavy docs).
        Presentations and press releases use pdfplumber (better tables).
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF not found: {file_path}")

        if doc_type == "transcript":
            text, page_count = self._extract_with_pymupdf(file_path)
            tables = []
            method = "pymupdf"
        else:
            text, tables, page_count = self._extract_with_pdfplumber(file_path)
            method = "pdfplumber"
            # Fall back to PyMuPDF if pdfplumber got very little text
            if len(text.strip()) < 100:
                text_alt, page_count = self._extract_with_pymupdf(file_path)
                if len(text_alt) > len(text):
                    text = text_alt
                    method = "pymupdf_fallback"

        quality = self._estimate_quality(text, page_count)

        return ExtractedDocument(
            file_path=file_path,
            doc_type=doc_type,
            text=text,
            tables=tables,
            page_count=page_count,
            extraction_method=method,
            quality_score=quality,
            char_count=len(text),
        )

    def _extract_with_pymupdf(self, file_path: str) -> Tuple[str, int]:
        """Fast text extraction using PyMuPDF."""
        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages), len(pages)

    def _extract_with_pdfplumber(self, file_path: str) -> Tuple[str, List[dict], int]:
        """Extract text and tables using pdfplumber."""
        text_parts = []
        all_tables = []

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

                tables = page.extract_tables()
                for table in tables:
                    if table and len(table) > 1:
                        headers = table[0] if table[0] else []
                        rows = table[1:]
                        all_tables.append({
                            "page": i + 1,
                            "headers": [str(h) if h else "" for h in headers],
                            "rows": [[str(c) if c else "" for c in row] for row in rows],
                        })

        return "\n\n".join(text_parts), all_tables, page_count

    def _estimate_quality(self, text: str, page_count: int) -> float:
        """Estimate extraction quality (0-1) based on text density."""
        if page_count == 0:
            return 0.0
        chars_per_page = len(text) / page_count
        # Good extraction: 500-3000 chars/page for text docs
        if chars_per_page >= 500:
            return min(1.0, chars_per_page / 2000)
        elif chars_per_page >= 100:
            return chars_per_page / 500
        else:
            return 0.1
