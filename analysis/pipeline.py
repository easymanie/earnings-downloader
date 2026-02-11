"""Analysis pipeline orchestrator."""

import json
import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

from analysis.extractor import PDFExtractor, ExtractedDocument
from analysis.llm.base import BaseLLMClient
from analysis.prompts.metrics import build_metrics_prompt
from analysis.prompts.themes import build_themes_prompt, build_industry_prompt, build_trend_prompt
from analysis.comparator import QuarterComparator
from core.models import (
    CompanyAnalysis, FinancialMetric, ManagementCommentary,
    QuarterComparison, IndustryAnalysis, IndustryTheme,
    MultiQuarterAnalysis, MetricTrend,
)
from core.storage.repositories import AnalysisRepository, ComparisonRepository, IndustryRepository
from config import config


class AnalysisError(Exception):
    pass


class AnalysisPipeline:
    """Orchestrates PDF extraction -> LLM analysis -> storage."""

    def __init__(
        self,
        extractor: PDFExtractor,
        llm_client: BaseLLMClient,
        analysis_repo: AnalysisRepository,
        comparison_repo: ComparisonRepository,
        industry_repo: Optional[IndustryRepository] = None,
    ):
        self.extractor = extractor
        self.llm = llm_client
        self.analysis_repo = analysis_repo
        self.comparison_repo = comparison_repo
        self.industry_repo = industry_repo
        self.comparator = QuarterComparator(
            material_threshold=config.material_change_pct,
            notable_threshold=config.notable_change_pct,
        )

    def analyze_company(
        self,
        company: str,
        quarter: str,
        year: str,
        force: bool = False,
    ) -> CompanyAnalysis:
        """Run full analysis pipeline for one company-quarter."""
        # Check cache
        if not force:
            existing = self.analysis_repo.get_analysis(company, quarter, year)
            if existing:
                return existing

        # Find downloaded PDFs
        pdfs = self._find_pdfs(company, quarter, year)
        if not pdfs:
            raise AnalysisError(
                f"No PDFs found for {company} {quarter} {year}. "
                f"Download documents first using the download feature."
            )

        # Extract text from all PDFs
        extracted_docs = []
        for pdf_path, doc_type in pdfs:
            try:
                doc = self.extractor.extract(pdf_path, doc_type)
                if doc.char_count > 50:  # Skip near-empty extractions
                    extracted_docs.append(doc)
            except Exception as e:
                print(f"  Warning: Failed to extract {pdf_path}: {e}")

        if not extracted_docs:
            raise AnalysisError(f"Could not extract text from any PDF for {company} {quarter} {year}")

        # Combine document texts
        combined_text = self._combine_documents(extracted_docs)

        # Truncate if exceeding LLM context
        max_chars = self.llm.max_context_tokens() * 3  # ~3 chars per token, leave room for prompts
        if len(combined_text) > max_chars:
            combined_text = combined_text[:max_chars]

        # Collect tables from all docs
        all_tables = []
        for doc in extracted_docs:
            all_tables.extend(doc.tables)

        # Extract metrics via LLM
        metrics = self._extract_metrics(company, quarter, year, combined_text, extracted_docs, all_tables)

        # Extract themes via LLM
        themes_data = self._extract_themes(company, quarter, year, combined_text)

        # Build result
        analysis = CompanyAnalysis(
            company=company,
            quarter=quarter,
            year=year,
            doc_types_analyzed=[d.doc_type for d in extracted_docs],
            metrics=metrics,
            commentary=themes_data.get("commentary", []),
            themes=themes_data.get("themes", []),
            key_highlights=themes_data.get("key_highlights", []),
            risks_flagged=themes_data.get("risks_flagged", []),
            guidance=themes_data.get("guidance"),
            analyzed_at=datetime.now(),
            llm_provider=self.llm.provider_name,
            llm_model=getattr(self.llm, "model", ""),
            source_files=[d.file_path for d in extracted_docs],
        )

        # Store
        self.analysis_repo.save_analysis(analysis)
        return analysis

    def analyze_multi_quarter(
        self,
        company: str,
        quarter: str,
        year: str,
        lookback: int = 4,
        force: bool = False,
    ) -> MultiQuarterAnalysis:
        """Analyze target quarter + preceding quarters, then synthesize trends."""
        # Build quarter list: target + lookback-1 preceding quarters
        quarter_list = [(quarter, year)]
        q, y = quarter, year
        for _ in range(lookback - 1):
            q, y = QuarterComparator.get_previous_quarter(q, y, "qoq")
            quarter_list.append((q, y))

        # Analyze each quarter (most recent first, reverse for chronological summary)
        analyses = []
        skipped = []
        for q, y in quarter_list:
            try:
                analysis = self.analyze_company(company, q, y, force)
                analyses.append(analysis)
            except AnalysisError:
                skipped.append(f"{q} {y}")

        if not analyses:
            raise AnalysisError(
                f"No PDFs found for {company} in any of the requested quarters. "
                f"Download documents first."
            )

        # Sort chronologically (oldest first) for the trend prompt
        analyses_chrono = sorted(
            analyses,
            key=lambda a: self._quarter_sort_key(a.quarter, a.year),
        )

        # Build summaries for LLM (oldest first)
        summaries = self._build_company_summaries(analyses_chrono)

        # Run trend synthesis via LLM
        system_prompt, user_prompt = build_trend_prompt(
            company=company,
            target_quarter=quarter,
            target_year=year,
            quarter_summaries=summaries,
            num_quarters=len(analyses),
        )
        response = self.llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.max_tokens_per_analysis,
            temperature=config.analysis_temperature,
        )
        trend_data = self._parse_json_response(response.content)

        # Build result (analyses in most-recent-first order for the UI)
        analyses_recent_first = sorted(
            analyses,
            key=lambda a: self._quarter_sort_key(a.quarter, a.year),
            reverse=True,
        )

        return MultiQuarterAnalysis(
            company=company,
            target_quarter=quarter,
            target_year=year,
            lookback_quarters=lookback,
            quarters_analyzed=[f"{a.quarter} {a.year}" for a in analyses_recent_first],
            quarter_analyses=analyses_recent_first,
            current_quarter_summary=trend_data.get("current_quarter_summary", ""),
            metric_trends=[
                MetricTrend(**t) if isinstance(t, dict) else MetricTrend(metric=str(t))
                for t in trend_data.get("metric_trends", [])
            ],
            persistent_themes=trend_data.get("persistent_themes", []),
            emerging_themes=trend_data.get("emerging_themes", []),
            fading_themes=trend_data.get("fading_themes", []),
            narrative_shifts=trend_data.get("narrative_shifts", []),
            consistency_assessment=trend_data.get("consistency_assessment", ""),
            analyzed_at=datetime.now(),
        )

    @staticmethod
    def _quarter_sort_key(quarter: str, year: str) -> tuple:
        """Sort key for chronological ordering of quarters."""
        fy = int(year[2:]) if year.startswith("FY") else int(year)
        q = int(quarter[1]) if quarter.startswith("Q") else 0
        return (fy, q)

    def compare_quarters(
        self,
        company: str,
        quarter: str,
        year: str,
        comparison_type: str = "qoq",
    ) -> Optional[QuarterComparison]:
        """Compare current quarter with previous."""
        current = self.analysis_repo.get_analysis(company, quarter, year)
        if not current:
            return None

        prev_q, prev_y = QuarterComparator.get_previous_quarter(quarter, year, comparison_type)
        previous = self.analysis_repo.get_analysis(company, prev_q, prev_y)
        if not previous:
            return None

        comparison = self.comparator.compare(current, previous, comparison_type)
        self.comparison_repo.save_comparison(comparison)
        return comparison

    def analyze_industry(
        self,
        industry: str,
        quarter: str,
        year: str,
        companies: List[str],
    ) -> IndustryAnalysis:
        """Run industry-level analysis across multiple companies."""
        # Gather individual analyses
        company_analyses = []
        for company in companies:
            analysis = self.analysis_repo.get_analysis(company, quarter, year)
            if analysis:
                company_analyses.append(analysis)

        if not company_analyses:
            raise AnalysisError(
                f"No analyzed companies found for {industry} in {quarter} {year}. "
                f"Analyze individual companies first."
            )

        # Build summaries for LLM
        summaries = self._build_company_summaries(company_analyses)

        # Generate industry narrative via LLM
        system_prompt, user_prompt = build_industry_prompt(industry, quarter, year, summaries)
        response = self.llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.max_tokens_per_analysis,
            temperature=config.analysis_temperature,
        )

        data = self._parse_json_response(response.content)

        analysis = IndustryAnalysis(
            industry=industry,
            quarter=quarter,
            year=year,
            companies_analyzed=[a.company for a in company_analyses],
            common_themes=[
                IndustryTheme(**t) if isinstance(t, dict) else IndustryTheme(theme=str(t))
                for t in data.get("common_themes", [])
            ],
            divergences=data.get("divergences", []),
            headline=data.get("headline", ""),
            narrative=data.get("narrative", ""),
            revenue_growth_range=data.get("revenue_growth_range"),
            margin_trend=data.get("margin_trend"),
            analyzed_at=datetime.now(),
        )

        if self.industry_repo:
            self.industry_repo.save_industry_analysis(analysis)

        return analysis

    def _find_pdfs(self, company: str, quarter: str, year: str) -> List[Tuple[str, str]]:
        """Find PDFs matching the quarter/year in any company directory."""
        downloads_dir = config.output_dir
        if not os.path.exists(downloads_dir):
            return []

        pattern = f"_{quarter}{year}_"
        results = []

        for dir_name in os.listdir(downloads_dir):
            dir_path = os.path.join(downloads_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue

            # Check if directory name matches the company (fuzzy)
            dir_lower = dir_name.lower().replace("_", " ")
            company_lower = company.lower()
            if company_lower not in dir_lower and dir_lower not in company_lower:
                # Try partial match
                company_words = company_lower.split()
                if not any(w in dir_lower for w in company_words if len(w) > 2):
                    continue

            for filename in os.listdir(dir_path):
                if not filename.lower().endswith(".pdf"):
                    continue
                if pattern.lower() in filename.lower():
                    # Determine doc_type from filename
                    doc_type = "transcript"
                    if "presentation" in filename.lower():
                        doc_type = "presentation"
                    elif "press_release" in filename.lower():
                        doc_type = "press_release"

                    results.append((os.path.join(dir_path, filename), doc_type))

        return results

    def _combine_documents(self, docs: List[ExtractedDocument]) -> str:
        """Combine multiple extracted documents with clear separators."""
        parts = []
        for doc in docs:
            label = doc.doc_type.upper().replace("_", " ")
            parts.append(f"=== {label} ({doc.page_count} pages) ===")
            parts.append(doc.text)
            if doc.tables:
                parts.append("=== EXTRACTED TABLES ===")
                for table in doc.tables[:5]:
                    headers = " | ".join(table.get("headers", []))
                    rows = "\n".join(" | ".join(row) for row in table.get("rows", [])[:20])
                    parts.append(f"Page {table.get('page', '?')}:\n{headers}\n{rows}")
        return "\n\n".join(parts)

    def _extract_metrics(
        self,
        company: str,
        quarter: str,
        year: str,
        combined_text: str,
        extracted_docs: List[ExtractedDocument],
        tables: list,
    ) -> List[FinancialMetric]:
        """Extract financial metrics via LLM."""
        system_prompt, user_prompt = build_metrics_prompt(
            company, quarter, year, "earnings documents", combined_text, tables
        )

        response = self.llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.max_tokens_per_analysis,
            temperature=config.analysis_temperature,
        )

        data = self._parse_json_response(response.content)
        metrics = []
        for m in data.get("metrics", []):
            if isinstance(m, dict):
                metrics.append(FinancialMetric(**m))

        return metrics

    def _extract_themes(
        self,
        company: str,
        quarter: str,
        year: str,
        combined_text: str,
    ) -> dict:
        """Extract themes, highlights, and commentary via LLM."""
        system_prompt, user_prompt = build_themes_prompt(company, quarter, year, combined_text)

        response = self.llm.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=config.max_tokens_per_analysis,
            temperature=config.analysis_temperature,
        )

        data = self._parse_json_response(response.content)

        # Parse themes
        themes = []
        for t in data.get("themes", []):
            if isinstance(t, dict):
                themes.append(t.get("theme", ""))
            elif isinstance(t, str):
                themes.append(t)

        # Parse commentary
        commentary = []
        for c in data.get("commentary", []):
            if isinstance(c, dict):
                commentary.append(ManagementCommentary(**c))

        return {
            "themes": [t for t in themes if t],
            "key_highlights": data.get("key_highlights", []),
            "risks_flagged": data.get("risks_flagged", []),
            "guidance": data.get("guidance"),
            "commentary": commentary,
        }

    def _build_company_summaries(self, analyses: List[CompanyAnalysis]) -> str:
        """Build a text summary of each company's results for industry analysis."""
        parts = []
        for a in analyses:
            lines = [f"### {a.company} ({a.quarter} {a.year})"]

            if a.metrics:
                lines.append("Key metrics:")
                for m in a.metrics:
                    val = f"{m.value:,.1f} {m.unit}" if m.value is not None else "N/A"
                    growth = f" (YoY: {m.yoy_growth:+.1f}%)" if m.yoy_growth is not None else ""
                    lines.append(f"  - {m.name}: {val}{growth}")

            if a.themes:
                lines.append(f"Themes: {', '.join(a.themes)}")

            if a.key_highlights:
                lines.append("Highlights:")
                for h in a.key_highlights[:5]:
                    lines.append(f"  - {h}")

            if a.guidance:
                lines.append(f"Guidance: {a.guidance}")

            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def _parse_json_response(self, content: str) -> dict:
        """Parse JSON from LLM response, handling markdown code fences."""
        text = content.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            print(f"  Warning: Could not parse LLM response as JSON. First 200 chars: {text[:200]}")
            return {}
