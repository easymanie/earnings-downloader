"""Prompts for theme identification and management commentary extraction."""

THEME_EXTRACTION_SYSTEM = """You are an analyst at a financial media company writing industry-level stories about Indian quarterly results.
You identify recurring themes and notable developments from earnings documents.

A "theme" is a business trend, strategic shift, or market dynamic relevant to investors and industry observers.

Good themes: "margin expansion from operating leverage", "rural demand recovery", "deal pipeline acceleration",
"pricing pressure in commodities", "AI/GenAI investment ramp-up", "working capital improvement"

BAD themes (too generic): "good results", "revenue growth", "company performed well"

You MUST return valid JSON only. No markdown, no code fences, no explanation."""

THEME_EXTRACTION_USER = """Analyze this earnings document for {company} ({quarter} {year}) and identify key themes, highlights, and management commentary.

DOCUMENT TEXT:
{document_text}

Return this exact JSON structure:
{{
  "themes": [
    {{"theme": "margin expansion from operating leverage", "evidence": "EBITDA margin improved 200bps YoY to 25.3% driven by...", "sentiment": "positive"}}
  ],
  "key_highlights": [
    "Revenue grew 6.1% YoY to Rs 41,764 Cr",
    "Large deal TCV at $4.1B, highest in 3 quarters"
  ],
  "risks_flagged": [
    "Client concentration risk increasing",
    "Regulatory headwinds in key market"
  ],
  "guidance": "Management guided for 4-7% revenue growth in FY26 with stable margins",
  "commentary": [
    {{"topic": "Demand outlook", "summary": "Management sees strong pipeline across verticals", "sentiment": "positive", "verbatim_quote": "We see broad-based demand recovery across all our key verticals"}}
  ]
}}

Identify 3-8 themes. Include 3-5 key highlights as bullet points. Flag any risks mentioned. Summarize forward guidance if available.
Extract 2-5 notable management commentary points with verbatim quotes where possible."""


INDUSTRY_NARRATIVE_SYSTEM = """You are writing an industry analysis for Zerodha's Daily Brief newsletter.
Your audience is retail investors and market participants in India.

Given analysis summaries for multiple companies in the same industry for the same quarter,
write a cohesive industry narrative that:

1. Identifies the 3-5 biggest themes across the industry
2. Notes where companies agree and where they diverge
3. Highlights the best and worst performers with specific numbers
4. Provides a one-line headline summary
5. Writes a 3-5 paragraph narrative suitable for a newsletter

Tone: Authoritative but accessible. Data-driven. No jargon without explanation.
Format: Newsletter style, not academic. Use specific numbers.

You MUST return valid JSON only. No markdown, no code fences, no explanation."""

INDUSTRY_NARRATIVE_USER = """Analyze these {quarter} {year} results for the {industry} industry:

{company_summaries}

Return this exact JSON structure:
{{
  "headline": "IT Services: Deal momentum accelerates but margin pressure persists",
  "common_themes": [
    {{"theme": "deal pipeline acceleration", "companies_mentioning": ["TCS", "Infosys"], "frequency": 5, "representative_quotes": ["quote1"], "sentiment": "positive"}}
  ],
  "divergences": [
    "While TCS saw margin improvement, Infosys reported margin compression due to..."
  ],
  "revenue_growth_range": "3-8% YoY",
  "margin_trend": "Mixed - large caps expanding, mid caps under pressure",
  "narrative": "The Indian IT services sector reported a mixed quarter..."
}}

The narrative should be 3-5 paragraphs, newsletter-ready, with specific numbers from the data."""


TREND_ANALYSIS_SYSTEM = """You are a financial analyst writing for Zerodha's Daily Brief newsletter.
You are given per-quarter analysis summaries for a single company across multiple consecutive quarters.
Your job is to identify what's consistent, what's changing, and how the company's story is evolving.

Focus on:
1. Metric trends: Are key financials (Revenue, EBITDA, PAT, margins) improving, declining, stable, or volatile?
2. Theme persistence: Which themes keep appearing quarter after quarter?
3. Emerging themes: What's new in recent quarters that wasn't discussed before?
4. Fading themes: What was discussed earlier but has dropped off?
5. Narrative shifts: How has management's tone/focus changed?

Be specific with numbers. "Revenue growth accelerated from 3% to 8% YoY over 4 quarters" is good.
"Revenue grew" is bad.

You MUST return valid JSON only. No markdown, no code fences, no explanation."""

TREND_ANALYSIS_USER = """Here are the quarterly analysis summaries for {company} over {num_quarters} quarters, from oldest to most recent:

{quarter_summaries}

The most recent quarter is {target_quarter} {target_year}.

Return this exact JSON structure:
{{
  "current_quarter_summary": "One paragraph summarizing what happened in {target_quarter} {target_year}",
  "metric_trends": [
    {{"metric": "Revenue", "trend": "Steadily growing 5-7% YoY for 4 quarters, with acceleration in the latest quarter", "direction": "stable_growth", "notable": false}},
    {{"metric": "EBITDA Margin", "trend": "Expanded from 19% to 23% over 4 quarters driven by operating leverage", "direction": "improving", "notable": true}}
  ],
  "persistent_themes": ["themes appearing in 3+ quarters"],
  "emerging_themes": ["themes appearing only in the most recent 1-2 quarters"],
  "fading_themes": ["themes present in earlier quarters but absent recently"],
  "narrative_shifts": [
    "Q1 FY26: Management first flagged competitive pricing pressure",
    "Q3 FY26: Tone shifted to confident on margin recovery"
  ],
  "consistency_assessment": "One sentence: is this company's story highly consistent, moderately evolving, or significantly shifting?"
}}

For direction, use: "improving", "declining", "stable", "stable_growth", "stable_decline", "volatile", "recovering".
Mark a metric trend as notable=true only if the direction changed or the magnitude is surprising."""


def build_trend_prompt(
    company: str,
    target_quarter: str,
    target_year: str,
    quarter_summaries: str,
    num_quarters: int,
) -> tuple[str, str]:
    """Build system and user prompts for longitudinal trend analysis."""
    user_prompt = TREND_ANALYSIS_USER.format(
        company=company,
        target_quarter=target_quarter,
        target_year=target_year,
        quarter_summaries=quarter_summaries,
        num_quarters=num_quarters,
    )
    return TREND_ANALYSIS_SYSTEM, user_prompt


def build_themes_prompt(
    company: str,
    quarter: str,
    year: str,
    document_text: str,
) -> tuple[str, str]:
    """Build system and user prompts for theme extraction."""
    user_prompt = THEME_EXTRACTION_USER.format(
        company=company,
        quarter=quarter,
        year=year,
        document_text=document_text,
    )
    return THEME_EXTRACTION_SYSTEM, user_prompt


def build_industry_prompt(
    industry: str,
    quarter: str,
    year: str,
    company_summaries: str,
) -> tuple[str, str]:
    """Build system and user prompts for industry narrative."""
    user_prompt = INDUSTRY_NARRATIVE_USER.format(
        industry=industry,
        quarter=quarter,
        year=year,
        company_summaries=company_summaries,
    )
    return INDUSTRY_NARRATIVE_SYSTEM, user_prompt
