"""SEC EDGAR data source for US company earnings documents."""

import re
import requests
from typing import List, Optional
from collections import defaultdict

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name, fuzzy_match_company
from config import config


class EdgarSource(BaseSource):
    """Fetches earnings documents from SEC EDGAR for US companies."""

    region = Region.US
    fiscal_year_type = FiscalYearType.CALENDAR
    source_name = "edgar"
    priority = 1

    # SEC EDGAR API endpoints
    COMPANY_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
    COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

    def __init__(self):
        self.session = requests.Session()
        # SEC requires User-Agent with company name and email
        self.session.headers.update({
            "User-Agent": "EarningsDownloader/1.0 (earnings-downloader@example.com)",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        })
        self._ticker_cache = None

    def _load_ticker_data(self) -> dict:
        """Load SEC company tickers mapping."""
        if self._ticker_cache is None:
            try:
                resp = self.session.get(self.COMPANY_TICKERS_URL, timeout=config.request_timeout)
                resp.raise_for_status()
                data = resp.json()
                # Build lookup by company name (normalized) and ticker
                self._ticker_cache = {}
                for _, info in data.items():
                    name = info.get("title", "").lower()
                    ticker = info.get("ticker", "").upper()
                    cik = str(info.get("cik_str", "")).zfill(10)
                    self._ticker_cache[name] = {"cik": cik, "ticker": ticker, "name": info.get("title", "")}
                    self._ticker_cache[ticker.lower()] = {"cik": cik, "ticker": ticker, "name": info.get("title", "")}
            except Exception as e:
                print(f"  Error loading SEC ticker data: {e}")
                self._ticker_cache = {}
        return self._ticker_cache

    def _find_company_cik(self, company_name: str) -> Optional[dict]:
        """Find company CIK number from name or ticker."""
        tickers = self._load_ticker_data()
        normalized = normalize_company_name(company_name).lower()

        # Direct match
        if normalized in tickers:
            return tickers[normalized]

        # Partial match on company name
        for key, info in tickers.items():
            if normalized in key or key in normalized:
                return info

        # Fuzzy match
        candidates = list(tickers.keys())
        matches = fuzzy_match_company(company_name, candidates, threshold=70)
        if matches:
            best_match = matches[0][0]
            return tickers[best_match]

        return None

    def search_company(self, query: str) -> Optional[dict]:
        """Search for a US company by name or ticker."""
        company_info = self._find_company_cik(query)
        if company_info:
            return {
                "name": company_info["name"],
                "ticker": company_info["ticker"],
                "cik": company_info["cik"],
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={company_info['cik']}&type=10-&dateb=&owner=include&count=40",
                "source": self.source_name,
                "region": self.region.value
            }
        return None

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
        """
        Get earnings documents from SEC EDGAR.

        Note: SEC EDGAR contains official filings (10-Q, 10-K, 8-K) but NOT
        earnings call transcripts. Those require third-party services.

        - 10-Q: Quarterly reports (contains P&L and financial statements)
        - 10-K: Annual reports (contains all financial statements)
        - 8-K: Current reports (press releases, material events)
        """
        calls = []

        company_info = self._find_company_cik(company_name)
        if not company_info:
            print(f"  Company not found in SEC database: {company_name}")
            return calls

        cik = company_info["cik"]
        actual_name = company_info["name"]

        try:
            # Fetch company submissions
            submissions_url = self.SUBMISSIONS_URL.format(cik=cik)
            resp = self.session.get(submissions_url, timeout=config.request_timeout)
            resp.raise_for_status()
            data = resp.json()

            filings = data.get("filings", {}).get("recent", {})

            forms = filings.get("form", [])
            dates = filings.get("filingDate", [])
            accessions = filings.get("accessionNumber", [])
            primary_docs = filings.get("primaryDocument", [])

            # Map forms to doc types they should produce
            # Each form can generate multiple doc type entries
            form_doc_types = {
                "10-Q": [],  # Built dynamically based on include flags
                "10-K": [],
                "8-K": [],
            }
            if include_transcripts:
                form_doc_types["10-Q"].append("transcript")
            if include_presentations:
                form_doc_types["10-K"].append("presentation")
            if include_press_releases:
                form_doc_types["8-K"].append("press_release")
            if include_pnl:
                form_doc_types["10-Q"].append("pnl")
            if include_annual_reports:
                form_doc_types["10-K"].append("annual_report")

            for i, form in enumerate(forms):
                if form not in form_doc_types:
                    continue

                doc_types_for_form = form_doc_types[form]
                if not doc_types_for_form:
                    continue

                # Parse date to quarter
                filing_date = dates[i] if i < len(dates) else ""
                quarter, year = self._parse_filing_date(filing_date, form)

                if not quarter:
                    continue

                # Build document URL
                accession = accessions[i].replace("-", "") if i < len(accessions) else ""
                primary_doc = primary_docs[i] if i < len(primary_docs) else ""

                if accession and primary_doc:
                    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{primary_doc}"

                    for doc_type in doc_types_for_form:
                        calls.append(EarningsCall(
                            company=actual_name,
                            quarter=quarter,
                            year=year,
                            doc_type=doc_type,
                            url=doc_url,
                            source=self.source_name
                        ))

        except Exception as e:
            print(f"  Error fetching from SEC EDGAR: {e}")

        return self._limit_by_quarter(calls, count)

    def _parse_filing_date(self, date_str: str, form: str) -> tuple[str, str]:
        """
        Parse SEC filing date to quarter and year.

        Calendar year quarters:
        Q1: Jan-Mar
        Q2: Apr-Jun
        Q3: Jul-Sep
        Q4: Oct-Dec
        """
        if not date_str:
            return "", ""

        try:
            # Date format: YYYY-MM-DD
            parts = date_str.split("-")
            year = parts[0]
            month = int(parts[1])

            # For 10-K, the filing is typically for the previous year
            if form == "10-K":
                return "FY", year

            # For 10-Q and 8-K, map to quarters
            if month in [1, 2, 3]:
                quarter = "Q4"  # Filing is for previous quarter
                year = str(int(year) - 1)
            elif month in [4, 5, 6]:
                quarter = "Q1"
            elif month in [7, 8, 9]:
                quarter = "Q2"
            else:
                quarter = "Q3"

            return quarter, year

        except Exception:
            return "", ""

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)

        for call in calls:
            quarter_key = (call.quarter, call.year)
            by_quarter[quarter_key].append(call)

        def quarter_sort_key(q):
            quarter, year = q
            try:
                y_num = int(year)
            except ValueError:
                y_num = 0
            q_num = int(quarter[1]) if quarter.startswith("Q") else 5  # FY comes last
            return (-y_num, -q_num)

        sorted_quarters = sorted(by_quarter.keys(), key=quarter_sort_key)

        result = []
        for quarter_key in sorted_quarters[:count]:
            result.extend(by_quarter[quarter_key])

        return result


# Auto-register when module is imported
SourceRegistry.register(EdgarSource())
