"""Prompts for financial metric extraction."""

METRIC_EXTRACTION_SYSTEM = """You are a financial analyst specializing in Indian equity markets.
You extract structured financial data from earnings documents.

CRITICAL RULES:
1. All monetary values MUST be in INR Crores. If a document uses lakhs, convert (divide by 100). If it uses millions USD, note this but still report as stated with unit "USD Mn".
2. Growth rates should be expressed as percentages with one decimal place.
3. Margins should be expressed as percentages of revenue.
4. If a value is not explicitly stated, return null. Do NOT estimate or calculate.
5. For quarterly data, prefer standalone quarterly figures (Q3 only) over cumulative (9M/YTD).
6. If both consolidated and standalone figures are present, prefer CONSOLIDATED.
7. Extract industry-specific KPIs where available (e.g., NIM for banks, ARPU for telecom, order book for infra).

You MUST return valid JSON only. No markdown, no code fences, no explanation."""

METRIC_EXTRACTION_USER = """Analyze this {doc_type} for {company} ({quarter} {year}) and extract all financial metrics.

DOCUMENT TEXT:
{document_text}

{table_context}

Return this exact JSON structure:
{{
  "metrics": [
    {{"name": "Revenue", "value": 1234.5, "unit": "INR Cr", "period": "{quarter} {year}", "yoy_growth": 12.5, "qoq_growth": 3.2, "margin": null, "raw_text": "Revenue at Rs 1,234.5 Cr, up 12.5% YoY"}}
  ],
  "period_type": "quarterly",
  "consolidation": "consolidated"
}}

Extract at minimum (if available): Revenue, EBITDA, EBITDA Margin, PAT (Net Profit), PAT Margin, EPS.
Also extract any segment revenues and industry-specific KPIs."""


def build_metrics_prompt(
    company: str,
    quarter: str,
    year: str,
    doc_type: str,
    document_text: str,
    tables: list,
) -> tuple[str, str]:
    """Build system and user prompts for metric extraction."""
    table_context = ""
    if tables:
        table_parts = []
        for t in tables[:10]:  # Limit to 10 most relevant tables
            headers = " | ".join(t.get("headers", []))
            rows = "\n".join(" | ".join(row) for row in t.get("rows", []))
            table_parts.append(f"Table (page {t.get('page', '?')}):\n{headers}\n{rows}")
        table_context = "EXTRACTED TABLES:\n" + "\n\n".join(table_parts)

    user_prompt = METRIC_EXTRACTION_USER.format(
        doc_type=doc_type,
        company=company,
        quarter=quarter,
        year=year,
        document_text=document_text,
        table_context=table_context,
    )
    return METRIC_EXTRACTION_SYSTEM, user_prompt
