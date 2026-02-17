"""BSE India data source for Indian company earnings documents."""

import re
import time
import requests
from datetime import datetime, timedelta
from typing import List, Optional
from collections import defaultdict

from ..base import BaseSource, Region, FiscalYearType
from ..registry import SourceRegistry
from core.models import EarningsCall, normalize_company_name
from config import config


# Release month → (quarter, FY year) mapping
# Months are RELEASE dates, not quarter-membership months
MONTH_TO_QUARTER = {
    1: ("Q3", 0),   # Jan release → Q3 of current FY
    2: ("Q3", 0),   # Feb release → Q3 of current FY
    3: ("Q4", 0),   # Mar release → Q4 of current FY
    4: ("Q4", 0),   # Apr release → Q4 of current FY
    5: ("Q4", 0),   # May release → Q4 of current FY
    6: ("Q1", 1),   # Jun release → Q1 of next FY
    7: ("Q1", 1),   # Jul release → Q1 of next FY
    8: ("Q1", 1),   # Aug release → Q1 of next FY
    9: ("Q2", 1),   # Sep release → Q2 of next FY
    10: ("Q2", 1),  # Oct release → Q2 of next FY
    11: ("Q2", 1),  # Nov release → Q2 of next FY
    12: ("Q3", 1),  # Dec release → Q3 of next FY
}

# BSE SUBCATNAME → doc_type mapping
BSE_DOC_TYPE_MAP = {
    "financial results": "pnl",
    "quarterly financial results": "pnl",
    "unaudited financial results": "pnl",
    "audited financial results": "pnl",
    "standalone financial results": "pnl",
    "consolidated financial results": "pnl",
    "half yearly results": "pnl",
    "annual audited results": "annual_report",
    "investor presentation": "presentation",
    "press release": "press_release",
    "transcript": "transcript",
    "earnings call transcript": "transcript",
    "outcome of board meeting": "press_release",
}

# Keyword fallbacks for HEADLINE/NEWSSUB classification
DOC_KEYWORDS = {
    "transcript": "transcript",
    "presentation": "presentation",
    "investor ppt": "presentation",
    "press release": "press_release",
    "balance sheet": "balance_sheet",
    "statement of financial position": "balance_sheet",
    "profit and loss": "pnl",
    "profit & loss": "pnl",
    "income statement": "pnl",
    "financial result": "pnl",
    "cash flow": "cash_flow",
    "cashflow": "cash_flow",
    "annual report": "annual_report",
    "integrated report": "annual_report",
}

# include_* flag mapping for doc_type filtering
DOC_TYPE_FLAGS = {
    "transcript": "include_transcripts",
    "presentation": "include_presentations",
    "press_release": "include_press_releases",
    "balance_sheet": "include_balance_sheets",
    "pnl": "include_pnl",
    "cash_flow": "include_cash_flow",
    "annual_report": "include_annual_reports",
}

_BSE_DELAY = 0.15  # ~7 req/sec (conservative)


def _extract_quarter_from_date(dt: datetime) -> tuple:
    """Map a filing date to (quarter, FY year string) using release-date semantics."""
    quarter, fy_offset = MONTH_TO_QUARTER[dt.month]
    fy_year = (dt.year + fy_offset) % 100
    return quarter, f"FY{fy_year:02d}"


def _extract_quarter_from_text(text: str) -> Optional[tuple]:
    """Try to extract explicit Q{n}FY{yy} from text."""
    m = re.search(r'Q([1-4])\s*(?:FY)?[\'"]?(\d{2,4})', text, re.IGNORECASE)
    if m:
        quarter = f"Q{m.group(1)}"
        yr = m.group(2)
        year = f"FY{yr}" if len(yr) == 2 else f"FY{int(yr) % 100:02d}"
        return quarter, year
    return None


class BSESource(BaseSource):
    """Fetches earnings filings from BSE India (bseindia.com)."""

    region = Region.INDIA
    fiscal_year_type = FiscalYearType.INDIAN
    source_name = "bse"
    priority = 0  # Official exchange filing

    API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"
    SEARCH_URL = f"{API_BASE}/PeerSmartSearch/w"
    ANNOUNCEMENTS_URL = f"{API_BASE}/AnnSubCategoryGetData/w"
    PDF_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachHis"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Origin": "https://www.bseindia.com",
            "Referer": "https://www.bseindia.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def _get(self, url: str, params: dict) -> requests.Response:
        """Make a rate-limited GET request."""
        time.sleep(_BSE_DELAY)
        resp = self.session.get(url, params=params, timeout=config.request_timeout)
        resp.raise_for_status()
        return resp

    def _search_scrip(self, query: str) -> Optional[dict]:
        """Search BSE for a company, return {scrip_code, name} or None."""
        try:
            resp = self._get(self.SEARCH_URL, {"Type": "SS", "text": query})
            text = resp.text.strip()

            if not text:
                return None

            # BSE returns pipe-separated values or HTML-like content
            # Try to find scrip codes (6-digit numbers) and company names
            # Format varies: could be "SCRIPCODE/COMPANY/ISIN/..." or HTML
            results = self._parse_search_results(text)
            if results:
                return results[0]
            return None
        except Exception as e:
            print(f"  BSE search failed for '{query}': {e}")
            return None

    def _parse_search_results(self, text: str) -> List[dict]:
        """Parse BSE search response into list of {scrip_code, name}."""
        results = []

        # Try JSON-like parsing first (some endpoints return JSON)
        try:
            import json
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        code = str(item.get("scrip_cd", item.get("SCRIP_CD", item.get("scripcode", ""))))
                        name = item.get("scrip_name", item.get("SCRIP_NAME", item.get("company", "")))
                        if code and name:
                            results.append({"scrip_code": code, "name": name})
                return results
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting from HTML-like response
        # Pattern: 6-digit scrip codes near company names
        scrip_matches = re.findall(
            r'<[^>]*?>\s*([A-Za-z][A-Za-z0-9 &.\'-]+?)\s*</[^>]*>.*?(\d{6})',
            text, re.DOTALL
        )
        if scrip_matches:
            for name, code in scrip_matches:
                results.append({"scrip_code": code, "name": name.strip()})
            return results

        # Reverse pattern: code then name
        scrip_matches = re.findall(
            r'(\d{6}).*?<[^>]*?>\s*([A-Za-z][A-Za-z0-9 &.\'-]+?)\s*</[^>]*>',
            text, re.DOTALL
        )
        if scrip_matches:
            for code, name in scrip_matches:
                results.append({"scrip_code": code, "name": name.strip()})
            return results

        # Fallback: just find any 6-digit numbers as potential scrip codes
        codes = re.findall(r'\b(\d{6})\b', text)
        if codes:
            results.append({"scrip_code": codes[0], "name": ""})

        return results

    def search_company(self, query: str) -> Optional[dict]:
        normalized = normalize_company_name(query)
        result = self._search_scrip(normalized)
        if not result:
            # Try original query if normalization didn't help
            if normalized != query:
                result = self._search_scrip(query)
        if not result:
            return None

        return {
            "name": result["name"] or query,
            "scrip_code": result["scrip_code"],
            "url": f"https://www.bseindia.com/stock-share-price/-/-/{result['scrip_code']}",
            "source": self.source_name,
            "region": self.region.value,
        }

    def suggest_companies(self, query: str, limit: int = 8) -> List[dict]:
        try:
            resp = self._get(self.SEARCH_URL, {"Type": "SS", "text": query})
            results = self._parse_search_results(resp.text.strip())
            return [
                {"name": r["name"] or query, "source": self.source_name, "region": self.region.value}
                for r in results[:limit]
                if r.get("name")
            ]
        except Exception:
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
        include_annual_reports: bool = True,
    ) -> List[EarningsCall]:
        flags = {
            "include_transcripts": include_transcripts,
            "include_presentations": include_presentations,
            "include_press_releases": include_press_releases,
            "include_balance_sheets": include_balance_sheets,
            "include_pnl": include_pnl,
            "include_cash_flow": include_cash_flow,
            "include_annual_reports": include_annual_reports,
        }

        try:
            company_info = self.search_company(company_name)
            if not company_info:
                return []

            scrip_code = company_info["scrip_code"]
            actual_name = company_info["name"]
            from_date, to_date = self._get_date_range(count)

            calls = []
            page = 1
            max_pages = 20  # Safety limit

            while page <= max_pages:
                data = self._fetch_announcements(scrip_code, from_date, to_date, page)
                rows = data.get("Table", [])
                if not rows:
                    break

                for row in rows:
                    call = self._parse_announcement(row, actual_name, flags)
                    if call:
                        calls.append(call)

                # Check pagination
                total_count = 0
                table1 = data.get("Table1", [])
                if table1:
                    total_count = table1[0].get("TotalPageCnt", table1[0].get("ROWCNT", 0))

                # If TotalPageCnt is the actual page count
                if total_count <= page:
                    break
                # If ROWCNT is total rows (25 per page)
                if total_count <= page * 25:
                    break

                page += 1

            return self._limit_by_quarter(calls, count)

        except Exception as e:
            print(f"  BSE get_earnings_calls failed for '{company_name}': {e}")
            return []

    def _get_date_range(self, count: int) -> tuple:
        """Return (from_date, to_date) as YYYYMMDD strings."""
        to_date = datetime.now()
        days_back = count * 92 + 180
        from_date = to_date - timedelta(days=days_back)
        return from_date.strftime("%Y%m%d"), to_date.strftime("%Y%m%d")

    def _fetch_announcements(self, scrip_code: str, from_date: str, to_date: str, page: int) -> dict:
        """Fetch one page of BSE announcements."""
        try:
            resp = self._get(self.ANNOUNCEMENTS_URL, {
                "pageno": page,
                "strCat": "Result",
                "subcategory": -1,
                "strPrevDate": from_date,
                "strToDate": to_date,
                "strSearch": "P",
                "strscrip": scrip_code,
                "strType": "C",
            })
            return resp.json()
        except Exception as e:
            print(f"  BSE announcements fetch failed (page {page}): {e}")
            return {}

    def _parse_announcement(self, row: dict, company_name: str, flags: dict) -> Optional[EarningsCall]:
        """Parse a single BSE announcement into an EarningsCall, or None if irrelevant."""
        attachment = row.get("ATTACHMENTNAME", "")
        if not attachment:
            return None

        # Classify document type
        doc_type = self._classify_doc_type(row)
        if not doc_type:
            return None

        # Check if this doc_type is enabled by flags
        flag_name = DOC_TYPE_FLAGS.get(doc_type)
        if flag_name and not flags.get(flag_name, True):
            return None

        # Extract quarter/year — try headline first, then filing date
        headline = row.get("NEWSSUB", "") or row.get("HEADLINE", "") or ""
        quarter_info = _extract_quarter_from_text(headline)

        if not quarter_info:
            filing_date = self._parse_datetime(row.get("DT_TM") or row.get("NEWS_DT", ""))
            if filing_date:
                quarter_info = _extract_quarter_from_date(filing_date)

        if not quarter_info:
            return None

        quarter, year = quarter_info
        pdf_url = f"{self.PDF_BASE}/{attachment}"
        filing_date = self._parse_datetime(row.get("DT_TM") or row.get("NEWS_DT", ""))

        return EarningsCall(
            company=company_name,
            quarter=quarter,
            year=year,
            doc_type=doc_type,
            url=pdf_url,
            source=self.source_name,
            date=filing_date,
        )

    def _classify_doc_type(self, row: dict) -> Optional[str]:
        """Classify a BSE announcement into a doc_type."""
        subcatname = (row.get("SUBCATNAME") or "").strip().lower()
        if subcatname and subcatname in BSE_DOC_TYPE_MAP:
            return BSE_DOC_TYPE_MAP[subcatname]

        # Fall back to keyword matching on headline
        headline = ((row.get("NEWSSUB") or "") + " " + (row.get("HEADLINE") or "")).lower()
        for keyword, dtype in DOC_KEYWORDS.items():
            if keyword in headline:
                return dtype

        # If category is "Result" but no specific match, assume pnl
        cat = (row.get("CATEGORYNAME") or "").lower()
        if "result" in cat:
            return "pnl"

        return None

    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse BSE datetime string."""
        if not dt_str:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S", "%Y%m%d"):
            try:
                return datetime.strptime(dt_str[:len(fmt.replace('%', 'X'))], fmt)
            except (ValueError, TypeError):
                continue
        # Try just extracting the date part
        try:
            return datetime.strptime(dt_str[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)
        for call in calls:
            by_quarter[(call.quarter, call.year)].append(call)

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
SourceRegistry.register(BSESource())
