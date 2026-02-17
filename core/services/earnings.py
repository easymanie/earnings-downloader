"""Earnings document service - shared business logic for CLI and API."""

import json
import os
from typing import List, Optional, Tuple

from sources import SourceRegistry
from sources.base import Region
from core.models import EarningsCall, deduplicate_calls


class EarningsService:
    """Business logic for earnings document operations."""

    def __init__(self):
        # Ensure sources are registered by importing them
        import sources.india  # noqa: F401
        import sources.us  # noqa: F401
        import sources.japan  # noqa: F401
        import sources.korea  # noqa: F401
        import sources.china  # noqa: F401

        # Load company aliases
        self._aliases = {}
        aliases_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "company_aliases.json")
        aliases_path = os.path.normpath(aliases_path)
        try:
            with open(aliases_path, "r") as f:
                self._aliases = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"  Warning: Could not load company aliases: {e}")

    def _resolve_alias(self, query: str) -> Tuple[str, Optional[str]]:
        """
        Check if query matches a company alias.

        Returns:
            (canonical_name, matched_alias) if alias found,
            (original_query, None) if no alias match.
        """
        normalized = query.strip().lower()

        # Exact match
        if normalized in self._aliases:
            return self._aliases[normalized], query.strip()

        # Partial match: check if query is a prefix of any alias
        for alias, canonical in self._aliases.items():
            if alias.startswith(normalized) and len(normalized) >= 3:
                return canonical, alias

        return query, None

    def search_company(
        self,
        query: str,
        region: Optional[Region] = None
    ) -> List[dict]:
        """
        Search for company across relevant sources.

        Args:
            query: Company name or search term
            region: Optional region to restrict search to

        Returns:
            List of company info dicts with name, url, source, region
        """
        resolved, _ = self._resolve_alias(query)

        if region:
            sources = SourceRegistry.get_sources(region)
        else:
            sources = SourceRegistry.get_all_sources()

        results = []
        for source in sources:
            result = source.search_company(resolved)
            if result:
                results.append(result)

        return results

    def suggest_companies(
        self,
        query: str,
        region: Optional[Region] = None,
        limit: int = 8
    ) -> List[dict]:
        """
        Get company name suggestions for autocomplete.

        Aggregates suggestions from all sources, deduplicates by name.
        Resolves aliases so brand names find official listed companies.
        """
        resolved, matched_alias = self._resolve_alias(query)

        if region:
            sources = SourceRegistry.get_sources(region)
        else:
            sources = SourceRegistry.get_all_sources()

        seen_names = set()
        suggestions = []

        if matched_alias:
            # Alias resolved — only search for canonical name, skip original query
            for source in sources:
                try:
                    results = source.suggest_companies(resolved, limit=limit)
                    for item in results:
                        name_lower = item["name"].lower()
                        if name_lower not in seen_names:
                            seen_names.add(name_lower)
                            item["alias"] = matched_alias
                            suggestions.append(item)
                except Exception as e:
                    print(f"  Suggest error from {source.source_name}: {e}")
        else:
            # No alias — search with original query
            for source in sources:
                try:
                    results = source.suggest_companies(query, limit=limit)
                    for item in results:
                        name_lower = item["name"].lower()
                        if name_lower not in seen_names:
                            seen_names.add(name_lower)
                            suggestions.append(item)
                except Exception as e:
                    print(f"  Suggest error from {source.source_name}: {e}")

        return suggestions[:limit]

    def get_earnings_documents(
        self,
        company_name: str,
        region: Optional[Region] = None,
        count: int = 5,
        include_transcripts: bool = True,
        include_presentations: bool = True,
        include_press_releases: bool = True,
        include_balance_sheets: bool = True,
        include_pnl: bool = True,
        include_cash_flow: bool = True,
        include_annual_reports: bool = True
    ) -> List[EarningsCall]:
        """
        Get earnings documents from all sources for a company.

        Args:
            company_name: Name of the company
            region: Optional region to restrict search to
            count: Number of quarters to fetch
            include_transcripts: Include earnings call transcripts
            include_presentations: Include investor presentations
            include_press_releases: Include press releases/fact sheets
            include_balance_sheets: Include balance sheet documents
            include_pnl: Include P&L / income statement documents
            include_cash_flow: Include cash flow statement documents
            include_annual_reports: Include annual reports

        Returns:
            Deduplicated list of EarningsCall objects
        """
        # Resolve alias before searching
        resolved, _ = self._resolve_alias(company_name)

        all_calls: List[EarningsCall] = []

        if region:
            sources = SourceRegistry.get_sources(region)
        else:
            sources = SourceRegistry.get_all_sources()

        for source in sources:
            try:
                calls = source.get_earnings_calls(
                    resolved,
                    count,
                    include_transcripts=include_transcripts,
                    include_presentations=include_presentations,
                    include_press_releases=include_press_releases,
                    include_balance_sheets=include_balance_sheets,
                    include_pnl=include_pnl,
                    include_cash_flow=include_cash_flow,
                    include_annual_reports=include_annual_reports
                )
                all_calls.extend(calls)
            except Exception as e:
                print(f"  Error from {source.source_name}: {e}")

        # Deduplicate - keeps highest priority source for each document
        return deduplicate_calls(all_calls)

    def get_available_regions(self) -> List[dict]:
        """
        Get list of available regions with their info.

        Returns:
            List of region info dicts
        """
        regions = []
        for region in SourceRegistry.get_regions():
            sources = SourceRegistry.get_sources(region)
            if sources:
                regions.append({
                    "id": region.value,
                    "name": region.name.title(),
                    "fiscal_year": sources[0].fiscal_year_type.value,
                    "sources": [s.source_name for s in sources]
                })
        return regions
