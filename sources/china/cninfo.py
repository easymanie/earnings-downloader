"""CNINFO data source for Chinese company earnings documents."""

import re
import requests
from typing import List, Optional
from collections import defaultdict
from datetime import datetime

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name, find_best_company_match
from config import config


class CninfoSource(BaseSource):
    """
    Fetches earnings documents from CNINFO for Chinese companies.

    CNINFO (cninfo.com.cn) is the official disclosure platform for
    Shenzhen Stock Exchange (SZSE) and Shanghai Stock Exchange (SSE) listed companies.

    This implementation uses known company mappings and public URLs.
    For full data access, consider using AKShare library.
    """

    region = Region.CHINA
    fiscal_year_type = FiscalYearType.CALENDAR
    source_name = "cninfo"
    priority = 1

    BASE_URL = "http://www.cninfo.com.cn"
    ENGLISH_URL = "http://www.cninfo.com.cn/new/index"

    # Known major Chinese companies (name -> company info)
    KNOWN_COMPANIES = {
        "alibaba": {"name": "Alibaba Group Holding Limited", "code": "BABA", "exchange": "NYSE"},
        "tencent": {"name": "Tencent Holdings Limited", "code": "0700", "exchange": "HKEX"},
        "byd": {"name": "BYD Company Limited", "code": "002594", "exchange": "SZSE"},
        "catl": {"name": "Contemporary Amperex Technology Co., Limited", "code": "300750", "exchange": "SZSE"},
        "kweichow moutai": {"name": "Kweichow Moutai Co., Ltd.", "code": "600519", "exchange": "SSE"},
        "moutai": {"name": "Kweichow Moutai Co., Ltd.", "code": "600519", "exchange": "SSE"},
        "icbc": {"name": "Industrial and Commercial Bank of China", "code": "601398", "exchange": "SSE"},
        "china construction bank": {"name": "China Construction Bank Corporation", "code": "601939", "exchange": "SSE"},
        "ping an": {"name": "Ping An Insurance (Group) Company of China", "code": "601318", "exchange": "SSE"},
        "china mobile": {"name": "China Mobile Limited", "code": "0941", "exchange": "HKEX"},
        "petrochina": {"name": "PetroChina Company Limited", "code": "601857", "exchange": "SSE"},
        "sinopec": {"name": "China Petroleum & Chemical Corporation", "code": "600028", "exchange": "SSE"},
        "bank of china": {"name": "Bank of China Limited", "code": "601988", "exchange": "SSE"},
        "agricultural bank": {"name": "Agricultural Bank of China Limited", "code": "601288", "exchange": "SSE"},
        "china life": {"name": "China Life Insurance Company Limited", "code": "601628", "exchange": "SSE"},
        "jd": {"name": "JD.com, Inc.", "code": "JD", "exchange": "NASDAQ"},
        "jd.com": {"name": "JD.com, Inc.", "code": "JD", "exchange": "NASDAQ"},
        "baidu": {"name": "Baidu, Inc.", "code": "BIDU", "exchange": "NASDAQ"},
        "netease": {"name": "NetEase, Inc.", "code": "NTES", "exchange": "NASDAQ"},
        "xiaomi": {"name": "Xiaomi Corporation", "code": "1810", "exchange": "HKEX"},
        "nio": {"name": "NIO Inc.", "code": "NIO", "exchange": "NYSE"},
        "xpeng": {"name": "XPeng Inc.", "code": "XPEV", "exchange": "NYSE"},
        "li auto": {"name": "Li Auto Inc.", "code": "LI", "exchange": "NASDAQ"},
        "huawei": {"name": "Huawei Technologies Co., Ltd.", "code": "N/A", "exchange": "Private"},
        "bytedance": {"name": "ByteDance Ltd.", "code": "N/A", "exchange": "Private"},
        "didi": {"name": "DiDi Global Inc.", "code": "DIDIY", "exchange": "OTC"},
        "midea": {"name": "Midea Group Co., Ltd.", "code": "000333", "exchange": "SZSE"},
        "gree": {"name": "Gree Electric Appliances Inc.", "code": "000651", "exchange": "SZSE"},
        "haier": {"name": "Haier Smart Home Co., Ltd.", "code": "600690", "exchange": "SSE"},
        "longi": {"name": "LONGi Green Energy Technology Co., Ltd.", "code": "601012", "exchange": "SSE"},
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5,zh-CN;q=0.3",
        })

    def _find_company(self, query: str) -> Optional[dict]:
        """Find company by name or stock code."""
        normalized = normalize_company_name(query).lower()

        # Direct match
        if normalized in self.KNOWN_COMPANIES:
            return self.KNOWN_COMPANIES[normalized]

        # Partial match
        for key, info in self.KNOWN_COMPANIES.items():
            if normalized in key or key in normalized:
                return info
            if normalized in info["name"].lower():
                return info

        # Fuzzy match
        best_match = find_best_company_match(query, self.KNOWN_COMPANIES, threshold=70)
        if best_match:
            return self.KNOWN_COMPANIES[best_match]

        return None

    def search_company(self, query: str) -> Optional[dict]:
        """Search for a Chinese company by name or stock code."""
        company_info = self._find_company(query)
        if company_info:
            exchange = company_info["exchange"]
            code = company_info["code"]

            # Determine URL based on exchange
            if exchange in ["SSE", "SZSE"]:
                url = f"{self.BASE_URL}/new/disclosure/stock?stockCode={code}"
            elif exchange in ["HKEX"]:
                url = f"https://www.hkexnews.hk/listedco/listconews/sehk/{code}/LTN.htm"
            else:
                url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={company_info['name']}"

            return {
                "name": company_info["name"],
                "ticker": code,
                "exchange": exchange,
                "url": url,
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
        Get earnings documents for a Chinese company.

        Chinese listed companies file:
        - Quarterly reports (季度报告)
        - Semi-annual reports (半年度报告)
        - Annual reports (年度报告)
        - Performance forecasts (业绩预告)

        Note: Most filings are in Chinese. US-listed Chinese companies
        file with SEC in English.
        """
        calls = []

        company_info = self._find_company(company_name)
        if not company_info:
            print(f"  Company not found in Chinese database: {company_name}")
            return calls

        actual_name = company_info["name"]
        stock_code = company_info["code"]
        exchange = company_info["exchange"]

        # Generate documents based on recent quarters (calendar year)
        current_year = datetime.now().year
        current_month = datetime.now().month
        current_quarter = (current_month - 1) // 3 + 1

        quarters_data = []
        q = current_quarter
        y = current_year

        for _ in range(count):
            q -= 1
            if q == 0:
                q = 4
                y -= 1
            quarters_data.append((f"Q{q}", str(y)))

        # Determine base URL based on exchange
        if exchange in ["SSE", "SZSE"]:
            base_url = f"{self.BASE_URL}/new/disclosure/stock?stockCode={stock_code}"
        elif exchange == "HKEX":
            base_url = f"https://www.hkexnews.hk/listedco/listconews/sehk/{stock_code}/LTN.htm"
        elif exchange in ["NYSE", "NASDAQ"]:
            base_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company={actual_name}&type=10-"
        else:
            base_url = f"https://www.google.com/search?q={actual_name}+investor+relations"

        # Create document entries
        for quarter, year in quarters_data[:count]:
            if include_transcripts:
                calls.append(EarningsCall(
                    company=actual_name,
                    quarter=quarter,
                    year=year,
                    doc_type="transcript",
                    url=base_url,
                    source=self.source_name
                ))

            if include_presentations:
                calls.append(EarningsCall(
                    company=actual_name,
                    quarter=quarter,
                    year=year,
                    doc_type="presentation",
                    url=base_url,
                    source=self.source_name
                ))

            if include_press_releases:
                calls.append(EarningsCall(
                    company=actual_name,
                    quarter=quarter,
                    year=year,
                    doc_type="press_release",
                    url=base_url,
                    source=self.source_name
                ))

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
SourceRegistry.register(CninfoSource())
