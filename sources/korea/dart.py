"""DART data source for Korean company earnings documents."""

import re
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict
from collections import defaultdict

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name, fuzzy_match_company
from config import config


class DartSource(BaseSource):
    """
    Fetches earnings documents from DART (Data Analysis, Retrieval and Transfer System).

    DART is Korea's official electronic disclosure system.
    API registration (free): https://opendart.fss.or.kr/

    Set environment variable: DART_API_KEY=your_api_key
    """

    region = Region.KOREA
    fiscal_year_type = FiscalYearType.CALENDAR
    source_name = "dart"
    priority = 1

    BASE_URL = "https://opendart.fss.or.kr/api"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
        })
        self._corp_codes: Optional[Dict[str, dict]] = None

    def _get_api_key(self) -> Optional[str]:
        """Get DART API key from config."""
        return config.dart_api_key

    def _load_corp_codes(self) -> Dict[str, dict]:
        """Load corporation codes from DART API."""
        if self._corp_codes is not None:
            return self._corp_codes

        api_key = self._get_api_key()
        if not api_key:
            print("  DART API key not configured. Set DART_API_KEY environment variable.")
            print("  Register for free at: https://opendart.fss.or.kr/")
            self._corp_codes = {}
            return self._corp_codes

        try:
            # Download corp code XML
            resp = self.session.get(
                f"{self.BASE_URL}/corpCode.xml",
                params={"crtfc_key": api_key},
                timeout=config.request_timeout
            )
            resp.raise_for_status()

            # Parse ZIP containing XML
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_content = zf.read("CORPCODE.xml")

            # Parse XML
            root = ET.fromstring(xml_content)
            self._corp_codes = {}

            for item in root.findall(".//list"):
                corp_code = item.findtext("corp_code", "")
                corp_name = item.findtext("corp_name", "")
                stock_code = item.findtext("stock_code", "")

                if corp_name and corp_code:
                    # Index by name (lowercase) and stock code
                    self._corp_codes[corp_name.lower()] = {
                        "corp_code": corp_code,
                        "corp_name": corp_name,
                        "stock_code": stock_code.strip() if stock_code else ""
                    }
                    if stock_code and stock_code.strip():
                        self._corp_codes[stock_code.strip()] = {
                            "corp_code": corp_code,
                            "corp_name": corp_name,
                            "stock_code": stock_code.strip()
                        }

            print(f"  Loaded {len(self._corp_codes)} Korean companies from DART")

        except Exception as e:
            print(f"  Error loading DART corp codes: {e}")
            self._corp_codes = {}

        return self._corp_codes

    def _find_company(self, query: str) -> Optional[dict]:
        """Find company by name or stock code."""
        corp_codes = self._load_corp_codes()
        if not corp_codes:
            return None

        normalized = normalize_company_name(query).lower()

        # Direct match
        if normalized in corp_codes:
            return corp_codes[normalized]

        # Partial match
        for key, info in corp_codes.items():
            if normalized in key or key in normalized:
                return info

        # Fuzzy match
        candidates = list(corp_codes.keys())
        matches = fuzzy_match_company(query, candidates, threshold=70)
        if matches:
            best_match = matches[0][0]
            return corp_codes[best_match]

        return None

    def search_company(self, query: str) -> Optional[dict]:
        """Search for a Korean company."""
        company_info = self._find_company(query)
        if company_info:
            return {
                "name": company_info["corp_name"],
                "ticker": company_info["stock_code"],
                "corp_code": company_info["corp_code"],
                "url": f"https://dart.fss.or.kr/dsab001/search.ax?textCrpNm={company_info['corp_name']}",
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
        """Get earnings documents from DART API."""
        calls = []
        api_key = self._get_api_key()

        if not api_key:
            return calls

        company_info = self._find_company(company_name)
        if not company_info:
            print(f"  Company not found in DART: {company_name}")
            return calls

        corp_code = company_info["corp_code"]
        actual_name = company_info["corp_name"]

        try:
            # Fetch disclosure list
            # pblntf_ty: A=정기공시(regular), B=주요사항(material), C=발행공시, D=지분공시, E=기타, F=외부감사, G=펀드, H=자산유동화, I=거래소, J=공정위, K=수시공시
            params = {
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bgn_de": "20200101",  # Start date
                "pblntf_ty": "A",  # Regular disclosures (quarterly/annual reports)
                "page_count": 100,
            }

            resp = self.session.get(
                f"{self.BASE_URL}/list.json",
                params=params,
                timeout=config.request_timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "000":
                print(f"  DART API error: {data.get('message', 'Unknown error')}")
                return calls

            disclosures = data.get("list", [])

            for disc in disclosures:
                report_nm = disc.get("report_nm", "")
                rcept_no = disc.get("rcept_no", "")
                rcept_dt = disc.get("rcept_dt", "")

                # Determine document type based on report name
                doc_type = None
                if "분기보고서" in report_nm or "사업보고서" in report_nm:
                    # Quarterly or annual report
                    if include_transcripts:
                        doc_type = "transcript"
                elif "실적" in report_nm or "영업" in report_nm:
                    if include_press_releases:
                        doc_type = "press_release"

                if not doc_type:
                    continue

                # Parse quarter from report name or date
                quarter, year = self._parse_report_info(report_nm, rcept_dt)
                if not quarter:
                    continue

                # Build document URL
                doc_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

                calls.append(EarningsCall(
                    company=actual_name,
                    quarter=quarter,
                    year=year,
                    doc_type=doc_type,
                    url=doc_url,
                    source=self.source_name
                ))

        except Exception as e:
            print(f"  Error fetching from DART: {e}")

        return self._limit_by_quarter(calls, count)

    def _parse_report_info(self, report_nm: str, rcept_dt: str) -> tuple[str, str]:
        """Parse quarter and year from report name and date."""
        # Try to extract from report name (e.g., "분기보고서 (2024.09)")
        match = re.search(r'\((\d{4})\.(\d{2})\)', report_nm)
        if match:
            year = match.group(1)
            month = int(match.group(2))

            if month in [3, 4]:
                return "Q1", year
            elif month in [6, 7]:
                return "Q2", year
            elif month in [9, 10]:
                return "Q3", year
            elif month in [12, 1]:
                return "Q4", year if month == 12 else str(int(year) - 1)

        # Fall back to receipt date
        if rcept_dt and len(rcept_dt) >= 6:
            year = rcept_dt[:4]
            month = int(rcept_dt[4:6])

            if month in [4, 5]:
                return "Q1", year
            elif month in [7, 8]:
                return "Q2", year
            elif month in [10, 11]:
                return "Q3", year
            elif month in [1, 2, 3]:
                return "Q4", str(int(year) - 1)

        return "", ""

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)

        for call in calls:
            quarter_key = (call.quarter, call.year)
            by_quarter[quarter_key].append(call)

        def quarter_sort_key(q):
            quarter, year = q
            q_num = int(quarter[1]) if quarter.startswith("Q") else 0
            try:
                y_num = int(year)
            except ValueError:
                y_num = 0
            return (-y_num, -q_num)

        sorted_quarters = sorted(by_quarter.keys(), key=quarter_sort_key)

        result = []
        for quarter_key in sorted_quarters[:count]:
            result.extend(by_quarter[quarter_key])

        return result


# Auto-register when module is imported
SourceRegistry.register(DartSource())
