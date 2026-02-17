"""Company Investor Relations website source for Indian company earnings documents."""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from collections import defaultdict

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name, find_best_company_match, fuzzy_match_company
from config import config


# Known IR page mappings for major Indian companies
KNOWN_IR_PAGES = {
    "reliance": "https://www.ril.com/investors/financial-reporting",
    "tcs": "https://www.tcs.com/investors",
    "infosys": "https://www.infosys.com/investors.html",
    "hdfc bank": "https://www.hdfcbank.com/personal/about-us/investor-relations",
    "icici bank": "https://www.icicibank.com/aboutus/investor-relations",
    "wipro": "https://www.wipro.com/investors/",
    "hcl tech": "https://www.hcltech.com/investors",
    "bharti airtel": "https://www.airtel.in/about-bharti/equity/results",
    "asian paints": "https://www.asianpaints.com/more/investors.html",
    "maruti suzuki": "https://www.marutisuzuki.com/corporate/investors",
    "motherson": "https://www.smrpbv.com/investor-relations.html",
    "samvardhana motherson": "https://www.smrpbv.com/investor-relations.html",
    "bajaj finance": "https://www.bajajfinserv.in/investor-relations",
    "kotak": "https://www.kotak.com/en/investor-relations.html",
    "axis bank": "https://www.axisbank.com/shareholders-corner",
    "itc": "https://www.itcportal.com/investor/index.aspx",
    "larsen": "https://www.larsentoubro.com/corporate/investor-relations/",
    "l&t": "https://www.larsentoubro.com/corporate/investor-relations/",
    "sun pharma": "https://www.sunpharma.com/investors",
    "titan": "https://www.titancompany.in/investors",
    "ultratech": "https://www.ultratechcement.com/investors",
    "nestle india": "https://www.nestle.in/investors",
    "power grid": "https://www.powergrid.in/investors",
    "ntpc": "https://www.ntpc.co.in/en/investors",
    "ongc": "https://ongcindia.com/web/eng/investors",
    "sbi": "https://www.sbi.co.in/web/investor-relations/investor-relations",
    "state bank": "https://www.sbi.co.in/web/investor-relations/investor-relations",
}


class CompanyIRSource(BaseSource):
    """Fetches earnings call data from company investor relations websites."""

    region = Region.INDIA
    fiscal_year_type = FiscalYearType.INDIAN
    source_name = "company_ir"
    priority = 2  # Tertiary - for factsheets not found in exchange filings

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def search_company(self, query: str) -> Optional[dict]:
        """Search for company - only returns info for known companies."""
        ir_url = self._find_ir_page(query)
        if ir_url:
            return {
                "name": query,
                "url": ir_url,
                "source": self.source_name,
                "region": self.region.value
            }
        return None

    def _find_ir_page(self, company_name: str) -> Optional[str]:
        """Find the investor relations page URL for a company."""
        normalized = normalize_company_name(company_name).lower()

        # Direct/partial match
        for key, url in KNOWN_IR_PAGES.items():
            if key in normalized or normalized in key:
                return url

        # Fuzzy match
        best_match = find_best_company_match(company_name, KNOWN_IR_PAGES, threshold=70)
        if best_match:
            return KNOWN_IR_PAGES[best_match]

        return None

    def suggest_companies(self, query: str, limit: int = 8) -> list[dict]:
        """Return company suggestions from known IR pages using fuzzy matching."""
        candidates = list(KNOWN_IR_PAGES.keys())
        matches = fuzzy_match_company(query, candidates, threshold=50)

        suggestions = []
        for name, score in matches[:limit]:
            suggestions.append({
                "name": name.title(),
                "source": self.source_name,
                "region": self.region.value
            })
        return suggestions

    def _extract_quarter_from_text(self, text: str) -> Tuple[str, str]:
        """Extract quarter and year from text."""
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

        q_match = re.search(r'Q([1-4])\s*(?:FY)?[\'"]?(\d{2,4})', text, re.IGNORECASE)
        if q_match:
            quarter = f"Q{q_match.group(1)}"
            year_str = q_match.group(2)
            year = f"FY{year_str}" if len(year_str) == 2 else f"FY{int(year_str) % 100:02d}"
            return quarter, year

        month_match = re.search(
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[\s,.-]+(\d{4})',
            text, re.IGNORECASE
        )
        if month_match:
            month = month_match.group(1).lower()
            year = month_match.group(2)
            if month in month_to_quarter:
                quarter, fy_func = month_to_quarter[month]
                return quarter, fy_func(year)

        return "", ""

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
        """Get earnings call documents from company IR website."""
        calls = []

        ir_url = self._find_ir_page(company_name)
        if not ir_url:
            return calls  # Silent return - Screener will be used as fallback

        print(f"  Checking IR page: {ir_url}")

        try:
            resp = self.session.get(ir_url, timeout=config.request_timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            base_url = f"{urlparse(ir_url).scheme}://{urlparse(ir_url).netloc}"

            all_links = soup.find_all("a", href=True)
            seen_urls = set()

            for link in all_links:
                href = link.get("href", "")
                text = link.get_text(" ", strip=True).lower()

                parent = link.find_parent(["li", "tr", "div", "p"])
                context = parent.get_text(" ", strip=True) if parent else text

                is_transcript = any(kw in text or kw in href.lower() for kw in [
                    "transcript", "concall", "con-call", "conference call",
                    "earnings call", "analyst call", "investor call"
                ])

                is_presentation = any(kw in text or kw in href.lower() for kw in [
                    "presentation", "ppt", "investor presentation", "results presentation"
                ])

                # Look for factsheet keywords (official company snapshots)
                is_factsheet = any(kw in text or kw in href.lower() for kw in [
                    "fact sheet", "factsheet", "fact-sheet",
                    "snapshot", "highlights", "key highlights",
                    "financial highlights", "results snapshot",
                    "quarterly snapshot", "performance snapshot"
                ])

                # Press releases from company website
                is_press_release = any(kw in text or kw in href.lower() for kw in [
                    "press release", "press-release", "media release",
                    "financial result", "results announcement", "outcome"
                ])

                # Combine: factsheet OR press release, but prefer PDFs
                is_press_release = (is_factsheet or is_press_release) and (
                    ".pdf" in href.lower() or is_factsheet
                )

                is_balance_sheet = any(kw in text or kw in href.lower() for kw in [
                    "balance sheet", "statement of financial position",
                    "assets and liabilities"
                ])

                is_pnl = any(kw in text or kw in href.lower() for kw in [
                    "profit and loss", "profit & loss", "p&l",
                    "income statement", "statement of profit",
                    "standalone results", "consolidated results",
                    "financial results"
                ])

                is_cash_flow = any(kw in text or kw in href.lower() for kw in [
                    "cash flow", "cashflow", "cash-flow"
                ])

                is_annual_report = any(kw in text or kw in href.lower() for kw in [
                    "annual report", "integrated report"
                ])

                doc_type = None
                if is_transcript and include_transcripts:
                    doc_type = "transcript"
                elif is_presentation and include_presentations:
                    doc_type = "presentation"
                elif is_press_release and include_press_releases:
                    doc_type = "press_release"
                elif is_balance_sheet and include_balance_sheets and ".pdf" in href.lower():
                    doc_type = "balance_sheet"
                elif is_pnl and include_pnl and ".pdf" in href.lower():
                    doc_type = "pnl"
                elif is_cash_flow and include_cash_flow and ".pdf" in href.lower():
                    doc_type = "cash_flow"
                elif is_annual_report and include_annual_reports and ".pdf" in href.lower():
                    doc_type = "annual_report"

                if not doc_type:
                    continue

                if href.startswith("http"):
                    full_url = href
                elif href.startswith("/"):
                    full_url = base_url + href
                else:
                    full_url = urljoin(ir_url, href)

                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                quarter, year = self._extract_quarter_from_text(context)
                if not quarter:
                    quarter, year = self._extract_quarter_from_text(href)
                if not quarter:
                    quarter, year = "Unknown", ""

                calls.append(EarningsCall(
                    company=company_name,
                    quarter=quarter,
                    year=year,
                    doc_type=doc_type,
                    url=full_url,
                    source=self.source_name
                ))

        except Exception as e:
            print(f"  Error fetching IR page: {e}")
            return calls

        return self._limit_by_quarter(calls, count)

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)

        for call in calls:
            quarter_key = (call.quarter, call.year)
            by_quarter[quarter_key].append(call)

        def quarter_sort_key(q):
            quarter, year = q
            q_num = int(quarter[1]) if quarter.startswith("Q") else 0
            y_num = int(year[2:]) if year.startswith("FY") and len(year) >= 4 else 0
            return (-y_num, -q_num)

        sorted_quarters = sorted(by_quarter.keys(), key=quarter_sort_key)

        result = []
        for quarter_key in sorted_quarters[:count]:
            result.extend(by_quarter[quarter_key])

        return result


# Auto-register when module is imported
SourceRegistry.register(CompanyIRSource())
