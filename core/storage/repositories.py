"""Data access layer for analysis results."""

import json
from datetime import datetime
from typing import Optional, List

from core.models import (
    CompanyAnalysis, FinancialMetric, ManagementCommentary,
    QuarterComparison, MaterialChange,
    IndustryAnalysis, IndustryTheme,
)
from .database import Database


class AnalysisRepository:
    """CRUD for company analysis results."""

    def __init__(self, db: Database):
        self.db = db

    def save_analysis(self, analysis: CompanyAnalysis) -> None:
        """Save or update a company analysis. Upserts on (company, quarter, year)."""
        self.db.execute(
            """INSERT INTO company_analyses
               (company, quarter, year, metrics_json, commentary_json, themes_json,
                highlights_json, risks_json, guidance, doc_types_analyzed,
                llm_provider, llm_model, source_files_json, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(company, quarter, year) DO UPDATE SET
                metrics_json=excluded.metrics_json,
                commentary_json=excluded.commentary_json,
                themes_json=excluded.themes_json,
                highlights_json=excluded.highlights_json,
                risks_json=excluded.risks_json,
                guidance=excluded.guidance,
                doc_types_analyzed=excluded.doc_types_analyzed,
                llm_provider=excluded.llm_provider,
                llm_model=excluded.llm_model,
                source_files_json=excluded.source_files_json,
                analyzed_at=excluded.analyzed_at""",
            (
                analysis.company,
                analysis.quarter,
                analysis.year,
                json.dumps([m.model_dump() for m in analysis.metrics]),
                json.dumps([c.model_dump() for c in analysis.commentary]),
                json.dumps(analysis.themes),
                json.dumps(analysis.key_highlights),
                json.dumps(analysis.risks_flagged),
                analysis.guidance,
                json.dumps(analysis.doc_types_analyzed),
                analysis.llm_provider,
                analysis.llm_model,
                json.dumps(analysis.source_files),
                analysis.analyzed_at.isoformat() if analysis.analyzed_at else datetime.now().isoformat(),
            ),
        )

    def get_analysis(self, company: str, quarter: str, year: str) -> Optional[CompanyAnalysis]:
        """Get a stored analysis by company/quarter/year."""
        row = self.db.fetchone(
            "SELECT * FROM company_analyses WHERE company=? AND quarter=? AND year=?",
            (company, quarter, year),
        )
        if not row:
            return None
        return self._row_to_analysis(row)

    def get_company_history(self, company: str, limit: int = 8) -> List[CompanyAnalysis]:
        """Get analysis history for a company, most recent first."""
        rows = self.db.fetchall(
            "SELECT * FROM company_analyses WHERE company=? ORDER BY analyzed_at DESC LIMIT ?",
            (company, limit),
        )
        return [self._row_to_analysis(r) for r in rows]

    def get_analyses_for_quarter(self, quarter: str, year: str) -> List[CompanyAnalysis]:
        """Get all analyses for a given quarter."""
        rows = self.db.fetchall(
            "SELECT * FROM company_analyses WHERE quarter=? AND year=?",
            (quarter, year),
        )
        return [self._row_to_analysis(r) for r in rows]

    def _row_to_analysis(self, row: dict) -> CompanyAnalysis:
        return CompanyAnalysis(
            company=row["company"],
            quarter=row["quarter"],
            year=row["year"],
            metrics=[FinancialMetric(**m) for m in json.loads(row["metrics_json"])],
            commentary=[ManagementCommentary(**c) for c in json.loads(row["commentary_json"])],
            themes=json.loads(row["themes_json"]),
            key_highlights=json.loads(row["highlights_json"]),
            risks_flagged=json.loads(row["risks_json"]),
            guidance=row["guidance"],
            doc_types_analyzed=json.loads(row["doc_types_analyzed"]),
            llm_provider=row["llm_provider"],
            llm_model=row["llm_model"],
            source_files=json.loads(row["source_files_json"]),
            analyzed_at=datetime.fromisoformat(row["analyzed_at"]) if row["analyzed_at"] else None,
        )


class ComparisonRepository:
    """CRUD for quarter comparison results."""

    def __init__(self, db: Database):
        self.db = db

    def save_comparison(self, comp: QuarterComparison) -> None:
        """Save or update a quarter comparison."""
        # Parse quarter and year from the combined string like "Q3 FY26"
        parts = comp.current_quarter.split()
        current_q = parts[0] if parts else comp.current_quarter
        current_y = parts[1] if len(parts) > 1 else ""

        self.db.execute(
            """INSERT INTO quarter_comparisons
               (company, current_quarter, current_year, previous_quarter, previous_year,
                comparison_type, changes_json, new_themes_json, dropped_themes_json, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(company, current_quarter, current_year, comparison_type) DO UPDATE SET
                previous_quarter=excluded.previous_quarter,
                previous_year=excluded.previous_year,
                changes_json=excluded.changes_json,
                new_themes_json=excluded.new_themes_json,
                dropped_themes_json=excluded.dropped_themes_json,
                summary=excluded.summary""",
            (
                comp.company,
                current_q,
                current_y,
                comp.previous_quarter,
                "",  # previous_year extracted from previous_quarter string
                comp.comparison_type,
                json.dumps([c.model_dump() for c in comp.material_changes]),
                json.dumps(comp.new_themes),
                json.dumps(comp.dropped_themes),
                comp.summary,
            ),
        )

    def get_comparison(
        self, company: str, quarter: str, year: str, comp_type: str
    ) -> Optional[QuarterComparison]:
        row = self.db.fetchone(
            """SELECT * FROM quarter_comparisons
               WHERE company=? AND current_quarter=? AND current_year=? AND comparison_type=?""",
            (company, quarter, year, comp_type),
        )
        if not row:
            return None
        return QuarterComparison(
            company=row["company"],
            current_quarter=f"{row['current_quarter']} {row['current_year']}",
            previous_quarter=row["previous_quarter"],
            comparison_type=row["comparison_type"],
            material_changes=[MaterialChange(**c) for c in json.loads(row["changes_json"])],
            new_themes=json.loads(row["new_themes_json"]),
            dropped_themes=json.loads(row["dropped_themes_json"]),
            summary=row["summary"],
        )


class IndustryRepository:
    """CRUD for industry mappings and analysis results."""

    def __init__(self, db: Database):
        self.db = db

    def get_all_industries(self) -> List[dict]:
        """Get all industries with their company lists."""
        rows = self.db.fetchall(
            "SELECT industry, GROUP_CONCAT(company) as companies FROM industry_mappings GROUP BY industry ORDER BY industry"
        )
        return [
            {"industry": r["industry"], "companies": r["companies"].split(",") if r["companies"] else []}
            for r in rows
        ]

    def get_companies_in_industry(self, industry: str) -> List[str]:
        rows = self.db.fetchall(
            "SELECT company FROM industry_mappings WHERE industry=? ORDER BY company",
            (industry,),
        )
        return [r["company"] for r in rows]

    def set_industry_mapping(self, industry: str, companies: List[str]) -> None:
        """Replace all companies for an industry."""
        self.db.execute("DELETE FROM industry_mappings WHERE industry=?", (industry,))
        for company in companies:
            self.db.execute(
                "INSERT OR IGNORE INTO industry_mappings (industry, company) VALUES (?, ?)",
                (industry, company),
            )

    def add_company_to_industry(self, industry: str, company: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO industry_mappings (industry, company) VALUES (?, ?)",
            (industry, company),
        )

    def save_industry_analysis(self, analysis: IndustryAnalysis) -> None:
        self.db.execute(
            """INSERT INTO industry_analyses
               (industry, quarter, year, companies_json, themes_json, divergences_json,
                headline, narrative, revenue_growth_range, margin_trend, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(industry, quarter, year) DO UPDATE SET
                companies_json=excluded.companies_json,
                themes_json=excluded.themes_json,
                divergences_json=excluded.divergences_json,
                headline=excluded.headline,
                narrative=excluded.narrative,
                revenue_growth_range=excluded.revenue_growth_range,
                margin_trend=excluded.margin_trend,
                analyzed_at=excluded.analyzed_at""",
            (
                analysis.industry,
                analysis.quarter,
                analysis.year,
                json.dumps(analysis.companies_analyzed),
                json.dumps([t.model_dump() for t in analysis.common_themes]),
                json.dumps(analysis.divergences),
                analysis.headline,
                analysis.narrative,
                analysis.revenue_growth_range,
                analysis.margin_trend,
                analysis.analyzed_at.isoformat() if analysis.analyzed_at else datetime.now().isoformat(),
            ),
        )

    def get_industry_analysis(
        self, industry: str, quarter: str, year: str
    ) -> Optional[IndustryAnalysis]:
        row = self.db.fetchone(
            "SELECT * FROM industry_analyses WHERE industry=? AND quarter=? AND year=?",
            (industry, quarter, year),
        )
        if not row:
            return None
        return IndustryAnalysis(
            industry=row["industry"],
            quarter=row["quarter"],
            year=row["year"],
            companies_analyzed=json.loads(row["companies_json"]),
            common_themes=[IndustryTheme(**t) for t in json.loads(row["themes_json"])],
            divergences=json.loads(row["divergences_json"]),
            headline=row["headline"],
            narrative=row["narrative"],
            revenue_growth_range=row["revenue_growth_range"],
            margin_trend=row["margin_trend"],
            analyzed_at=datetime.fromisoformat(row["analyzed_at"]) if row["analyzed_at"] else None,
        )

    def seed_from_json(self, json_path: str) -> None:
        """Seed industry mappings from a JSON file if table is empty."""
        existing = self.db.fetchall("SELECT COUNT(*) as cnt FROM industry_mappings")
        if existing and existing[0]["cnt"] > 0:
            return

        import json as json_mod
        with open(json_path) as f:
            data = json_mod.load(f)

        for industry_name, info in data.get("industries", {}).items():
            for company in info.get("companies", []):
                self.db.execute(
                    "INSERT OR IGNORE INTO industry_mappings (industry, company) VALUES (?, ?)",
                    (industry_name, company),
                )
