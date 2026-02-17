"""Screener.in data source for Indian company earnings documents."""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import urljoin
from collections import defaultdict

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name
from config import config


class ScreenerSource(BaseSource):
    """Fetches earnings call data from Screener.in (any Indian company)."""

    region = Region.INDIA
    fiscal_year_type = FiscalYearType.INDIAN
    source_name = "screener"
    priority = 0  # Primary source - links to BSE/NSE filings

    BASE_URL = "https://www.screener.in"
    SEARCH_URL = "https://www.screener.in/api/company/search/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def search_company(self, query: str) -> Optional[dict]:
        """Search for company and return its info."""
        normalized = normalize_company_name(query)
        try:
            resp = self.session.get(
                self.SEARCH_URL,
                params={"q": normalized},
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            results = resp.json()

            if not results:
                return None

            first = results[0]
            return {
                "name": first.get("name", query),
                "url": urljoin(self.BASE_URL, first.get("url", "")),
                "source": self.source_name,
                "region": self.region.value
            }

        except Exception as e:
            print(f"  Search error: {e}")
            return None

    def suggest_companies(self, query: str, limit: int = 8) -> list[dict]:
        """Return multiple company suggestions from Screener.in search API."""
        normalized = normalize_company_name(query)
        try:
            resp = self.session.get(
                self.SEARCH_URL,
                params={"q": normalized},
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            results = resp.json()

            suggestions = []
            for item in results[:limit]:
                suggestions.append({
                    "name": item.get("name", ""),
                    "source": self.source_name,
                    "region": self.region.value
                })
            return suggestions

        except Exception as e:
            print(f"  Suggest error: {e}")
            return []

    def get_earnings_calls(
        self,
        company_name: str,
        count: int = 5,
        include_transcripts: bool = True,
        include_presentations: bool = True,
        include_press_releases: bool = True,
        include_balance_sheets: bool = True,
        include_pnl: bool = True,
        include_cash_flow: bool = True,
        include_annual_reports: bool = True
    ) -> List[EarningsCall]:
        """Get earnings call documents for a company."""
        calls = []

        # Search for company
        company_info = self.search_company(company_name)
        if not company_info:
            print(f"  Company not found on Screener.in: {company_name}")
            return calls

        company_url = company_info["url"]

        try:
            resp = self.session.get(company_url, timeout=config.request_timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Get actual company name from page
            name_elem = soup.select_one("h1.margin-0")
            actual_name = name_elem.text.strip() if name_elem else company_name

            # Find documents section
            doc_section = self._find_concall_section(soup)
            if not doc_section:
                print(f"  No documents section found for {company_name}")
                return calls

            # Parse document entries
            entries = self._parse_concall_entries(
                doc_section, actual_name,
                include_transcripts=include_transcripts,
                include_presentations=include_presentations,
                include_press_releases=include_press_releases,
                include_balance_sheets=include_balance_sheets,
                include_pnl=include_pnl,
                include_cash_flow=include_cash_flow,
                include_annual_reports=include_annual_reports
            )
            calls.extend(entries)

        except Exception as e:
            print(f"  Error fetching from Screener.in: {e}")

        return self._limit_by_quarter(calls, count)

    def _find_concall_section(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Find the concalls/documents section."""
        doc_section = soup.find(id="documents")
        if doc_section:
            return doc_section

        doc_section = soup.find("section", {"id": re.compile(r"document|concall", re.I)})
        if doc_section:
            return doc_section

        for section in soup.find_all(["div", "section"]):
            classes = section.get("class", [])
            if any("concall" in c.lower() or "document" in c.lower() for c in classes):
                return section

        all_links = soup.find_all("a", href=re.compile(r"(bseindia|nseindia).*\.pdf", re.I))
        if all_links:
            return all_links[0].find_parent("section") or all_links[0].find_parent("div")

        return None

    def _parse_concall_entries(
        self,
        section: BeautifulSoup,
        company_name: str,
        include_transcripts: bool = True,
        include_presentations: bool = True,
        include_press_releases: bool = True,
        include_balance_sheets: bool = True,
        include_pnl: bool = True,
        include_cash_flow: bool = True,
        include_annual_reports: bool = True
    ) -> List[EarningsCall]:
        """Parse earnings call entries from section."""
        calls = []
        seen_urls = set()

        # Month-to-quarter mapping for RELEASE DATES (Indian FY: Apr-Mar).
        # Documents are published ~1-2 months after quarter ends, so the
        # month here is when results were released, not the quarter itself.
        # e.g. Oct/Nov = Q2 results (Jul-Sep), Jan/Feb = Q3 results (Oct-Dec)
        month_to_quarter = {
            "jan": ("Q3", lambda y: f"FY{(int(y) % 100):02d}"),
            "feb": ("Q3", lambda y: f"FY{(int(y) % 100):02d}"),
            "mar": ("Q4", lambda y: f"FY{(int(y) % 100):02d}"),
            "apr": ("Q4", lambda y: f"FY{(int(y) % 100):02d}"),
            "may": ("Q4", lambda y: f"FY{(int(y) % 100):02d}"),
            "jun": ("Q1", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "jul": ("Q1", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "aug": ("Q1", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "sep": ("Q2", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "oct": ("Q2", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "nov": ("Q2", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "dec": ("Q3", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
        }

        def extract_date_info(text: str) -> tuple[str, str]:
            """Extract quarter and fiscal year from text."""
            q_match = re.search(r'Q([1-4])\s*(?:FY)?(\d{2,4})', text, re.IGNORECASE)
            if q_match:
                quarter = f"Q{q_match.group(1)}"
                year_str = q_match.group(2)
                year = f"FY{year_str}" if len(year_str) == 2 else f"FY{int(year_str) % 100:02d}"
                return quarter, year

            month_match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{4})', text, re.IGNORECASE)
            if month_match:
                month = month_match.group(1).lower()
                year = month_match.group(2)
                if month in month_to_quarter:
                    quarter, fy_func = month_to_quarter[month]
                    return quarter, fy_func(year)

            return "", ""

        def add_call(href, context, doc_type):
            if not href or href in seen_urls:
                return
            seen_urls.add(href)
            quarter, year = extract_date_info(context)
            if not quarter:
                quarter, year = "Unknown", ""
            full_url = href if href.startswith("http") else urljoin(self.BASE_URL, href)
            calls.append(EarningsCall(
                company=company_name,
                quarter=quarter,
                year=year,
                doc_type=doc_type,
                url=full_url,
                source=self.source_name
            ))

        if include_transcripts:
            transcript_links = section.find_all("a", string=re.compile(r"transcript", re.I))
            for link in transcript_links:
                parent_li = link.find_parent("li")
                context = parent_li.get_text(" ", strip=True) if parent_li else ""
                add_call(link.get("href", ""), context, "transcript")

        if include_presentations:
            ppt_links = section.find_all("a", string=re.compile(r"ppt|presentation", re.I))
            for link in ppt_links:
                parent_li = link.find_parent("li")
                context = parent_li.get_text(" ", strip=True) if parent_li else ""
                add_call(link.get("href", ""), context, "presentation")

        if include_press_releases:
            all_links = section.find_all("a", href=True)
            for link in all_links:
                text = link.get_text(strip=True).lower()
                href = link.get("href", "").lower()

                # Only accept PDFs from official sources
                is_official_source = any(domain in href for domain in [
                    "bseindia.com", "nseindia.com",
                    # Company domains are OK too
                ])

                # Must be a PDF
                is_pdf = ".pdf" in href

                # Look for factsheet/press release keywords
                is_factsheet = any(kw in text or kw in href for kw in [
                    "fact sheet", "factsheet", "fact-sheet",
                    "snapshot", "highlights", "key highlights",
                    "financial highlights", "results snapshot"
                ])

                is_press_release = any(kw in text for kw in [
                    "press release", "press-release", "media release",
                    "outcome", "financial result"
                ])

                parent = link.find_parent("li") or link.find_parent("div")
                parent_text = parent.get_text(" ", strip=True).lower() if parent else ""

                # Accept if: (factsheet OR press release from official source) AND is PDF
                if is_pdf and (is_factsheet or (is_press_release and is_official_source)):
                    context = parent.get_text(" ", strip=True) if parent else text
                    add_call(link.get("href", ""), context, "press_release")

        # Financial statement document types
        if include_balance_sheets or include_pnl or include_cash_flow or include_annual_reports:
            all_links = section.find_all("a", href=True)
            for link in all_links:
                text = link.get_text(strip=True).lower()
                href = link.get("href", "").lower()

                is_pdf = ".pdf" in href
                if not is_pdf:
                    continue

                parent = link.find_parent("li") or link.find_parent("div")
                context = parent.get_text(" ", strip=True) if parent else text

                if include_balance_sheets and any(kw in text or kw in href for kw in [
                    "balance sheet", "statement of financial position",
                    "assets and liabilities"
                ]):
                    add_call(link.get("href", ""), context, "balance_sheet")

                elif include_pnl and any(kw in text or kw in href for kw in [
                    "profit and loss", "profit & loss", "p&l",
                    "income statement", "statement of profit",
                    "standalone results", "consolidated results",
                    "financial results"
                ]):
                    add_call(link.get("href", ""), context, "pnl")

                elif include_cash_flow and any(kw in text or kw in href for kw in [
                    "cash flow", "cashflow", "cash-flow"
                ]):
                    add_call(link.get("href", ""), context, "cash_flow")

                elif include_annual_reports and any(kw in text or kw in href for kw in [
                    "annual report", "integrated report"
                ]):
                    add_call(link.get("href", ""), context, "annual_report")

        return calls

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)

        for call in calls:
            quarter_key = (call.quarter, call.year)
            by_quarter[quarter_key].append(call)

        def quarter_sort_key(q):
            quarter, year = q
            q_num = int(quarter[1]) if quarter.startswith("Q") else 0
            y_num = int(year[2:]) if year.startswith("FY") else 0
            return (-y_num, -q_num)

        sorted_quarters = sorted(by_quarter.keys(), key=quarter_sort_key)

        result = []
        for quarter_key in sorted_quarters[:count]:
            result.extend(by_quarter[quarter_key])

        return result


# Auto-register when module is imported
SourceRegistry.register(ScreenerSource())
