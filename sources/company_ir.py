"""Company Investor Relations website source for earnings call transcripts."""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from utils import EarningsCall, normalize_company_name

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


class CompanyIRSource:
    """Fetches earnings call data from company investor relations websites."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def _find_ir_page(self, company_name: str) -> Optional[str]:
        """Find the investor relations page URL for a company."""
        normalized = normalize_company_name(company_name).lower()

        # Check known mappings
        for key, url in KNOWN_IR_PAGES.items():
            if key in normalized or normalized in key:
                return url

        # Try to search for IR page
        try:
            search_url = f"https://www.google.com/search?q={company_name}+investor+relations+india"
            # Note: Google search scraping is unreliable, so we'll rely on known mappings
            # and return None for unknown companies
            return None
        except Exception:
            return None

    def _extract_quarter_from_text(self, text: str) -> Tuple[str, str]:
        """Extract quarter and year from text."""
        # Month to quarter mapping (Indian FY)
        month_to_quarter = {
            "jan": ("Q3", lambda y: f"FY{(int(y) % 100):02d}"),
            "feb": ("Q3", lambda y: f"FY{(int(y) % 100):02d}"),
            "mar": ("Q4", lambda y: f"FY{(int(y) % 100):02d}"),
            "apr": ("Q4", lambda y: f"FY{(int(y) % 100):02d}"),
            "may": ("Q1", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "jun": ("Q1", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "jul": ("Q1", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "aug": ("Q2", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "sep": ("Q2", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "oct": ("Q2", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "nov": ("Q3", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
            "dec": ("Q3", lambda y: f"FY{((int(y) + 1) % 100):02d}"),
        }

        # Try Q format first
        q_match = re.search(r'Q([1-4])\s*(?:FY)?[\'"]?(\d{2,4})', text, re.IGNORECASE)
        if q_match:
            quarter = f"Q{q_match.group(1)}"
            year_str = q_match.group(2)
            year = f"FY{year_str}" if len(year_str) == 2 else f"FY{int(year_str) % 100:02d}"
            return quarter, year

        # Try month-year format
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
        include_press_releases: bool = True
    ) -> List[EarningsCall]:
        """Get earnings call documents from company IR website."""
        calls = []

        ir_url = self._find_ir_page(company_name)
        if not ir_url:
            print(f"  No known IR page for {company_name}, will use Screener.in")
            return calls

        print(f"  Checking IR page: {ir_url}")

        try:
            resp = self.session.get(ir_url, timeout=config.request_timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            base_url = f"{urlparse(ir_url).scheme}://{urlparse(ir_url).netloc}"

            # Find all PDF links that might be transcripts, presentations, or press releases
            all_links = soup.find_all("a", href=True)
            seen_urls = set()

            for link in all_links:
                href = link.get("href", "")
                text = link.get_text(" ", strip=True).lower()

                # Get parent context
                parent = link.find_parent(["li", "tr", "div", "p"])
                context = parent.get_text(" ", strip=True) if parent else text

                # Check document type
                is_transcript = any(kw in text or kw in href.lower() for kw in [
                    "transcript", "concall", "con-call", "conference call",
                    "earnings call", "analyst call", "investor call"
                ])

                is_presentation = any(kw in text or kw in href.lower() for kw in [
                    "presentation", "ppt", "investor presentation", "results presentation"
                ])

                is_press_release = any(kw in text or kw in href.lower() for kw in [
                    "press release", "press-release", "media release",
                    "fact sheet", "factsheet", "fact-sheet",
                    "financial result", "results announcement", "outcome"
                ])

                # Determine doc_type and check if we should include it
                doc_type = None
                if is_transcript and include_transcripts:
                    doc_type = "transcript"
                elif is_presentation and include_presentations:
                    doc_type = "presentation"
                elif is_press_release and include_press_releases:
                    doc_type = "press_release"

                if not doc_type:
                    continue

                # Build full URL
                if href.startswith("http"):
                    full_url = href
                elif href.startswith("/"):
                    full_url = base_url + href
                else:
                    full_url = urljoin(ir_url, href)

                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                # Extract quarter info
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
                    source="company_ir"
                ))

        except Exception as e:
            print(f"  Error fetching IR page: {e}")
            return calls

        # Sort by quarter (most recent first) and limit
        return self._limit_by_quarter(calls, count)

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        from collections import defaultdict
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
