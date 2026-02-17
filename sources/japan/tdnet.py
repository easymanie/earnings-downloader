"""J-Quants/TDnet data source for Japanese company earnings documents."""

import re
import requests
from typing import List, Optional, Dict
from collections import defaultdict
from datetime import datetime, timedelta

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name, fuzzy_match_company
from config import config


class TdnetSource(BaseSource):
    """
    Fetches earnings documents using J-Quants API for Japanese companies.

    J-Quants is JPX's official market data API with a free tier.
    Registration: https://www.jpx-jquants.com/

    Set environment variables:
    - TDNET_API_ID=your_email
    - TDNET_API_PASSWORD=your_password
    """

    region = Region.JAPAN
    fiscal_year_type = FiscalYearType.JAPANESE  # Apr-Mar
    source_name = "tdnet"
    priority = 1

    AUTH_URL = "https://api.jquants.com/v1/token/auth_user"
    REFRESH_URL = "https://api.jquants.com/v1/token/auth_refresh"
    LISTED_URL = "https://api.jquants.com/v1/listed/info"
    STATEMENTS_URL = "https://api.jquants.com/v1/fins/statements"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Content-Type": "application/json",
        })
        self._id_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._companies: Optional[Dict[str, dict]] = None

    def _get_credentials(self) -> tuple[Optional[str], Optional[str]]:
        """Get J-Quants credentials from config."""
        return config.tdnet_api_id, config.tdnet_api_password

    def _authenticate(self) -> bool:
        """Authenticate with J-Quants API."""
        if self._id_token:
            return True

        api_id, api_password = self._get_credentials()
        if not api_id or not api_password:
            print("  J-Quants API credentials not configured.")
            print("  Set TDNET_API_ID and TDNET_API_PASSWORD environment variables.")
            print("  Register for free at: https://www.jpx-jquants.com/")
            return False

        try:
            # Get refresh token
            resp = self.session.post(
                self.AUTH_URL,
                json={"mailaddress": api_id, "password": api_password},
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            data = resp.json()
            self._refresh_token = data.get("refreshToken")

            if not self._refresh_token:
                print(f"  J-Quants auth failed: {data}")
                return False

            # Get ID token
            resp = self.session.post(
                self.REFRESH_URL,
                params={"refreshtoken": self._refresh_token},
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            data = resp.json()
            self._id_token = data.get("idToken")

            if self._id_token:
                self.session.headers["Authorization"] = f"Bearer {self._id_token}"
                return True

        except Exception as e:
            print(f"  J-Quants authentication error: {e}")

        return False

    def _load_companies(self) -> Dict[str, dict]:
        """Load listed companies from J-Quants API."""
        if self._companies is not None:
            return self._companies

        if not self._authenticate():
            self._companies = {}
            return self._companies

        try:
            resp = self.session.get(
                self.LISTED_URL,
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            data = resp.json()

            self._companies = {}
            for item in data.get("info", []):
                code = item.get("Code", "")
                name = item.get("CompanyName", "")
                name_en = item.get("CompanyNameEnglish", "")

                if code and name:
                    info = {
                        "code": code,
                        "name": name,
                        "name_en": name_en or name,
                        "sector": item.get("Sector33CodeName", ""),
                        "market": item.get("MarketCodeName", ""),
                    }
                    self._companies[code] = info
                    self._companies[name.lower()] = info
                    if name_en:
                        self._companies[name_en.lower()] = info

            print(f"  Loaded {len(data.get('info', []))} Japanese companies from J-Quants")

        except Exception as e:
            print(f"  Error loading J-Quants companies: {e}")
            self._companies = {}

        return self._companies

    def _find_company(self, query: str) -> Optional[dict]:
        """Find company by name or code."""
        companies = self._load_companies()
        if not companies:
            return None

        normalized = normalize_company_name(query).lower()

        # Direct match by code or name
        if normalized in companies:
            return companies[normalized]

        # Partial match
        for key, info in companies.items():
            if isinstance(key, str) and (normalized in key or key in normalized):
                return info

        # Fuzzy match
        candidates = [k for k in companies.keys() if isinstance(k, str)]
        matches = fuzzy_match_company(query, candidates, threshold=70)
        if matches:
            best_match = matches[0][0]
            return companies[best_match]

        return None

    def search_company(self, query: str) -> Optional[dict]:
        """Search for a Japanese company."""
        company_info = self._find_company(query)
        if company_info:
            return {
                "name": company_info["name_en"],
                "ticker": company_info["code"],
                "market": company_info.get("market", ""),
                "url": f"https://www.jpx.co.jp/english/listing/co-search/index.html?q={company_info['code']}",
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
        """Get earnings documents from J-Quants API."""
        calls = []

        if not self._authenticate():
            return calls

        company_info = self._find_company(company_name)
        if not company_info:
            print(f"  Company not found in J-Quants: {company_name}")
            return calls

        code = company_info["code"]
        actual_name = company_info["name_en"]

        try:
            # Fetch financial statements
            resp = self.session.get(
                self.STATEMENTS_URL,
                params={"code": code},
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            data = resp.json()

            statements = data.get("statements", [])

            for stmt in statements:
                disclosed_date = stmt.get("DisclosedDate", "")
                type_of_doc = stmt.get("TypeOfDocument", "")

                # Parse fiscal period
                fiscal_year = stmt.get("FiscalYear", "")
                fiscal_quarter = stmt.get("FiscalQuarter", "")

                if not fiscal_year:
                    continue

                # Determine quarter
                if fiscal_quarter:
                    quarter = f"Q{fiscal_quarter}"
                else:
                    quarter = "FY"

                # Year in Japanese FY format
                year = f"FY{int(fiscal_year) % 100:02d}"

                # Document type based on TypeOfDocument
                # 1Q, 2Q, 3Q = quarterly, FY = annual
                doc_type = "transcript"  # Earnings summaries

                if include_transcripts:
                    # TDnet document URL
                    doc_url = f"https://www.release.tdnet.info/inbs/I_main_00.html?q={code}"

                    calls.append(EarningsCall(
                        company=actual_name,
                        quarter=quarter,
                        year=year,
                        doc_type=doc_type,
                        url=doc_url,
                        source=self.source_name
                    ))

        except Exception as e:
            print(f"  Error fetching from J-Quants: {e}")

        return self._limit_by_quarter(calls, count)

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)

        for call in calls:
            quarter_key = (call.quarter, call.year)
            by_quarter[quarter_key].append(call)

        def quarter_sort_key(q):
            quarter, year = q
            q_num = int(quarter[1]) if quarter.startswith("Q") else 5
            y_num = int(year[2:]) if year.startswith("FY") else 0
            return (-y_num, -q_num)

        sorted_quarters = sorted(by_quarter.keys(), key=quarter_sort_key)

        result = []
        for quarter_key in sorted_quarters[:count]:
            result.extend(by_quarter[quarter_key])

        return result


# Auto-register when module is imported
SourceRegistry.register(TdnetSource())
