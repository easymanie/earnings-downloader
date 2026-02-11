"""Analysis service - shared business logic for analysis operations."""

import os
from typing import List, Optional, Tuple

from analysis.extractor import PDFExtractor
from analysis.llm import get_llm_client
from analysis.pipeline import AnalysisPipeline
from analysis.comparator import QuarterComparator
from core.models import CompanyAnalysis, QuarterComparison, IndustryAnalysis, MultiQuarterAnalysis
from core.storage.database import Database
from core.storage.repositories import AnalysisRepository, ComparisonRepository, IndustryRepository
from config import config


class AnalysisService:
    """Business logic for analysis operations. Shared between API and CLI."""

    def __init__(self):
        self.db = Database(config.analysis_db_path)
        self.analysis_repo = AnalysisRepository(self.db)
        self.comparison_repo = ComparisonRepository(self.db)
        self.industry_repo = IndustryRepository(self.db)
        self.extractor = PDFExtractor()

        # Seed industry mappings from JSON if empty
        seed_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "industries.json"
        )
        if os.path.exists(seed_path):
            self.industry_repo.seed_from_json(seed_path)

    def _get_pipeline(self, provider: Optional[str] = None) -> AnalysisPipeline:
        llm = get_llm_client(provider)
        return AnalysisPipeline(
            extractor=self.extractor,
            llm_client=llm,
            analysis_repo=self.analysis_repo,
            comparison_repo=self.comparison_repo,
            industry_repo=self.industry_repo,
        )

    def analyze_company(
        self,
        company: str,
        quarter: str,
        year: str,
        force: bool = False,
        provider: Optional[str] = None,
    ) -> CompanyAnalysis:
        """Analyze a single company's earnings for a quarter."""
        pipeline = self._get_pipeline(provider)
        return pipeline.analyze_company(company, quarter, year, force)

    def analyze_companies(
        self,
        companies: List[str],
        quarter: str,
        year: str,
        force: bool = False,
        provider: Optional[str] = None,
    ) -> Tuple[List[CompanyAnalysis], List[dict]]:
        """Analyze multiple companies. Returns (results, errors)."""
        results = []
        errors = []
        pipeline = self._get_pipeline(provider)

        for company in companies:
            try:
                analysis = pipeline.analyze_company(company, quarter, year, force)
                results.append(analysis)
            except Exception as e:
                errors.append({"company": company, "error": str(e)})

        return results, errors

    def get_analysis(
        self,
        company: str,
        quarter: Optional[str] = None,
        year: Optional[str] = None,
    ) -> Optional[CompanyAnalysis] | List[CompanyAnalysis]:
        """Get stored analysis results."""
        if quarter and year:
            return self.analysis_repo.get_analysis(company, quarter, year)
        return self.analysis_repo.get_company_history(company)

    def analyze_with_context(
        self,
        company: str,
        quarter: str,
        year: str,
        lookback: int = 4,
        force: bool = False,
        provider: Optional[str] = None,
    ) -> MultiQuarterAnalysis:
        """Analyze a company's quarter with N preceding quarters for trend context."""
        pipeline = self._get_pipeline(provider)
        return pipeline.analyze_multi_quarter(company, quarter, year, lookback, force)

    def compare_quarters(
        self,
        company: str,
        quarter: str,
        year: str,
        comparison_type: str = "qoq",
    ) -> Optional[QuarterComparison]:
        """Compare current quarter with previous."""
        pipeline = self._get_pipeline()
        return pipeline.compare_quarters(company, quarter, year, comparison_type)

    def analyze_industry(
        self,
        industry: str,
        quarter: str,
        year: str,
        force: bool = False,
        provider: Optional[str] = None,
    ) -> IndustryAnalysis:
        """Run industry-level analysis."""
        companies = self.industry_repo.get_companies_in_industry(industry)
        if not companies:
            raise ValueError(f"No companies mapped to industry: {industry}")

        # Analyze any missing companies first
        pipeline = self._get_pipeline(provider)
        for company in companies:
            existing = self.analysis_repo.get_analysis(company, quarter, year)
            if not existing or force:
                try:
                    pipeline.analyze_company(company, quarter, year, force)
                except Exception as e:
                    print(f"  Warning: Could not analyze {company}: {e}")

        return pipeline.analyze_industry(industry, quarter, year, companies)

    def get_industries(self) -> List[dict]:
        """Get all industries with their company lists."""
        return self.industry_repo.get_all_industries()

    def get_industry_analysis(
        self, industry: str, quarter: str, year: str
    ) -> Optional[IndustryAnalysis]:
        """Get stored industry analysis."""
        return self.industry_repo.get_industry_analysis(industry, quarter, year)

    def update_industry_companies(self, industry: str, companies: List[str]) -> None:
        """Update the company list for an industry."""
        self.industry_repo.set_industry_mapping(industry, companies)

    def create_industry(self, name: str, companies: List[str]) -> None:
        """Create a new industry grouping."""
        self.industry_repo.set_industry_mapping(name, companies)
