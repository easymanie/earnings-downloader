"""Data models for earnings downloader."""

import re
from typing import Optional, List, Tuple
from datetime import datetime
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process


# --- Analysis Models ---


class FinancialMetric(BaseModel):
    """A single financial metric extracted from an earnings document."""
    name: str
    value: Optional[float] = None
    unit: str = "INR Cr"
    period: str = ""
    yoy_growth: Optional[float] = None
    qoq_growth: Optional[float] = None
    margin: Optional[float] = None
    raw_text: str = ""


class ManagementCommentary(BaseModel):
    """Key management commentary point from a transcript."""
    topic: str
    summary: str
    sentiment: str = "neutral"
    verbatim_quote: Optional[str] = None


class CompanyAnalysis(BaseModel):
    """Complete analysis result for one company-quarter."""
    company: str
    quarter: str
    year: str
    doc_types_analyzed: List[str] = Field(default_factory=list)
    metrics: List[FinancialMetric] = Field(default_factory=list)
    commentary: List[ManagementCommentary] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    key_highlights: List[str] = Field(default_factory=list)
    risks_flagged: List[str] = Field(default_factory=list)
    guidance: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    llm_provider: str = ""
    llm_model: str = ""
    source_files: List[str] = Field(default_factory=list)


class MaterialChange(BaseModel):
    """A material change flagged in QoQ/YoY comparison."""
    metric_name: str
    current_value: Optional[float] = None
    previous_value: Optional[float] = None
    change_pct: Optional[float] = None
    direction: str = ""
    significance: str = ""
    context: str = ""


class QuarterComparison(BaseModel):
    """Comparison between two quarters for a company."""
    company: str
    current_quarter: str
    previous_quarter: str
    comparison_type: str
    material_changes: List[MaterialChange] = Field(default_factory=list)
    new_themes: List[str] = Field(default_factory=list)
    dropped_themes: List[str] = Field(default_factory=list)
    summary: str = ""


class MetricTrend(BaseModel):
    """Trend of a single metric across multiple quarters."""
    metric: str
    trend: str = ""
    direction: str = "stable"
    notable: bool = False


class MultiQuarterAnalysis(BaseModel):
    """Multi-quarter longitudinal analysis for a single company."""
    company: str
    target_quarter: str
    target_year: str
    lookback_quarters: int = 4
    quarters_analyzed: List[str] = Field(default_factory=list)

    # Per-quarter data (most recent first)
    quarter_analyses: List[CompanyAnalysis] = Field(default_factory=list)

    # Longitudinal synthesis
    current_quarter_summary: str = ""
    metric_trends: List[MetricTrend] = Field(default_factory=list)
    persistent_themes: List[str] = Field(default_factory=list)
    emerging_themes: List[str] = Field(default_factory=list)
    fading_themes: List[str] = Field(default_factory=list)
    narrative_shifts: List[str] = Field(default_factory=list)
    consistency_assessment: str = ""

    analyzed_at: Optional[datetime] = None


class IndustryTheme(BaseModel):
    """A theme identified across multiple companies in an industry."""
    theme: str
    companies_mentioning: List[str] = Field(default_factory=list)
    frequency: int = 0
    representative_quotes: List[str] = Field(default_factory=list)
    sentiment: str = "neutral"


class IndustryAnalysis(BaseModel):
    """Industry-level analysis aggregating multiple companies."""
    industry: str
    quarter: str
    year: str
    companies_analyzed: List[str] = Field(default_factory=list)
    revenue_growth_range: Optional[str] = None
    margin_trend: Optional[str] = None
    common_themes: List[IndustryTheme] = Field(default_factory=list)
    divergences: List[str] = Field(default_factory=list)
    headline: str = ""
    narrative: str = ""
    analyzed_at: Optional[datetime] = None


# --- Download Models ---


class EarningsCall(BaseModel):
    """Represents an earnings call document."""

    company: str = Field(..., description="Company name")
    quarter: str = Field(..., description="Quarter (e.g., 'Q3', 'Q4')")
    year: str = Field(..., description="Fiscal year (e.g., 'FY26', '2025')")
    doc_type: str = Field(..., description="Document type: transcript, presentation, press_release")
    url: str = Field(..., description="Download URL")
    source: str = Field(..., description="Source name: screener, company_ir, edgar, etc.")
    date: Optional[datetime] = Field(None, description="Document date if available")

    class Config:
        frozen = True  # Make hashable for deduplication

    def get_filename(self) -> str:
        """Generate filename for this document."""
        ext = self._get_extension()
        safe_company = re.sub(r'[^\w\s-]', '', self.company)
        safe_company = safe_company.strip().replace(' ', '_')[:50]
        return f"{safe_company}_{self.quarter}{self.year}_{self.doc_type}{ext}"

    def _get_extension(self) -> str:
        """Determine file extension from URL or doc type."""
        url_lower = self.url.lower()
        if '.pdf' in url_lower:
            return '.pdf'
        elif '.ppt' in url_lower or '.pptx' in url_lower:
            return '.pptx'
        elif '.mp3' in url_lower or '.wav' in url_lower:
            return '.mp3'
        elif self.doc_type == 'presentation':
            return '.pdf'
        return '.pdf'


def normalize_company_name(name: str) -> str:
    """Normalize company name for searching."""
    suffixes = [
        ' Ltd', ' Limited', ' Ltd.', ' Inc', ' Inc.', ' Corp', ' Corporation',
        ' Co.', ' Co', ' Company', ' PLC', ' plc', ' NV', ' SA', ' AG', ' SE',
        ' Holdings', ' Group', ' International', ' Intl',
    ]
    normalized = name.strip()
    for suffix in suffixes:
        if normalized.lower().endswith(suffix.lower()):
            normalized = normalized[:-len(suffix)]
    # Remove extra whitespace
    normalized = ' '.join(normalized.split())
    return normalized.strip()


def fuzzy_match_company(
    query: str,
    candidates: List[str],
    threshold: int = 60
) -> List[Tuple[str, int]]:
    """
    Fuzzy match a company name against a list of candidates.

    Args:
        query: Search query
        candidates: List of company names to match against
        threshold: Minimum match score (0-100)

    Returns:
        List of (company_name, score) tuples, sorted by score descending
    """
    if not candidates:
        return []

    normalized_query = normalize_company_name(query).lower()

    # Use rapidfuzz for fuzzy matching
    results = process.extract(
        normalized_query,
        candidates,
        scorer=fuzz.WRatio,  # Weighted ratio handles partial matches well
        limit=10
    )

    # Filter by threshold and return
    return [(name, score) for name, score, _ in results if score >= threshold]


def find_best_company_match(
    query: str,
    company_dict: dict,
    threshold: int = 60
) -> Optional[str]:
    """
    Find the best matching company key from a dictionary.

    Args:
        query: Search query
        company_dict: Dictionary with company names/keys
        threshold: Minimum match score

    Returns:
        Best matching key or None
    """
    candidates = list(company_dict.keys())
    matches = fuzzy_match_company(query, candidates, threshold)

    if matches:
        return matches[0][0]  # Return the best match
    return None


def parse_quarter_year(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract quarter and year from text like 'Q3FY26' or 'Q3 2025'."""
    match = re.search(r'Q([1-4])\s*(?:FY)?(\d{2,4})', text, re.IGNORECASE)
    if match:
        quarter = f"Q{match.group(1)}"
        year_str = match.group(2)
        if len(year_str) == 2:
            year = f"FY{year_str}"
        else:
            year = year_str
        return quarter, year
    return None, None


def deduplicate_calls(calls: list[EarningsCall]) -> list[EarningsCall]:
    """Remove duplicate earnings calls, preferring certain sources."""

    # Priority: lower number = higher priority (preferred)
    # 1. NSE/BSE official filings
    # 2. Screener/Tijori (aggregators that link to exchange filings)
    # 3. Company IR website (factsheets, additional materials)
    source_priority = {
        "bse": 0,
        "nse": 0,
        "screener": 1,
        "trendlyne": 1,
        "tijori": 1,
        "company_ir": 2,
        "edgar": 0,  # Official SEC filings (US)
        "tdnet": 0,  # Official Japan filings
        "dart": 0,   # Official Korea filings
        "cninfo": 0, # Official China filings
    }

    # First pass: deduplicate by URL (exact same document)
    seen_urls = {}
    for call in calls:
        url_key = call.url.lower().rstrip('/')
        if url_key not in seen_urls:
            seen_urls[url_key] = call
        else:
            existing = seen_urls[url_key]
            if source_priority.get(call.source, 99) < source_priority.get(existing.source, 99):
                seen_urls[url_key] = call

    # Second pass: deduplicate by (company, quarter, year, doc_type)
    seen = {}  # (normalized_company, quarter, year, doc_type) -> call
    for call in seen_urls.values():
        # Normalize company name for better matching
        normalized_company = normalize_company_name(call.company).lower()
        key = (normalized_company, call.quarter, call.year, call.doc_type)
        if key not in seen:
            seen[key] = call
        else:
            existing = seen[key]
            if source_priority.get(call.source, 99) < source_priority.get(existing.source, 99):
                seen[key] = call

    return list(seen.values())
