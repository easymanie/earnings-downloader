"""NSE India data source for Indian company earnings documents."""

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


# Release month → (quarter, FY year offset) mapping
# Months are RELEASE dates, not quarter-membership months
MONTH_TO_QUARTER = {
    1: ("Q3", 0),   # Jan release → Q3 of current FY
    2: ("Q3", 0),
    3: ("Q4", 0),
    4: ("Q4", 0),
    5: ("Q4", 0),
    6: ("Q1", 1),   # Jun release → Q1 of next FY
    7: ("Q1", 1),
    8: ("Q1", 1),
    9: ("Q2", 1),
    10: ("Q2", 1),
    11: ("Q2", 1),
    12: ("Q3", 1),
}

# NSE desc → doc_type mapping (exact lowercase match)
NSE_DOC_TYPE_MAP = {
    "financial results": "pnl",
    "quarterly results": "pnl",
    "financial result updates": "pnl",
    "integrated filing- financial": "pnl",
    "investor presentation": "presentation",
    "press release": "press_release",
    "outcome of board meeting": "press_release",
    "earnings call transcript": "transcript",
    "transcript": "transcript",
    "analysts/institutional investor meet/con. call updates": "transcript",
    "annual report": "annual_report",
}

# Keyword fallbacks for desc/attchmntText classification
NSE_DOC_KEYWORDS = {
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

# include_* flag mapping
DOC_TYPE_FLAGS = {
    "transcript": "include_transcripts",
    "presentation": "include_presentations",
    "press_release": "include_press_releases",
    "balance_sheet": "include_balance_sheets",
    "pnl": "include_pnl",
    "cash_flow": "include_cash_flow",
    "annual_report": "include_annual_reports",
}

_NSE_DELAY = 0.35  # ~3 req/sec
_COOKIE_TTL_SECONDS = 55
_MAX_REQUESTS_PER_SESSION = 8


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


class NSESource(BaseSource):
    """Fetches earnings filings from NSE India (nseindia.com)."""

    region = Region.INDIA
    fiscal_year_type = FiscalYearType.INDIAN
    source_name = "nse"
    priority = 0  # Official exchange filing

    BASE_URL = "https://www.nseindia.com"
    AUTOCOMPLETE_URL = f"{BASE_URL}/api/search/autocomplete"
    ANNOUNCEMENTS_URL = f"{BASE_URL}/api/corporate-announcements"
    ANNUAL_REPORTS_URL = f"{BASE_URL}/api/annual-reports"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
        })
        self._cookie_expiry: Optional[datetime] = None
        self._request_count: int = 0

    def _refresh_cookies(self, symbol: str = "TCS") -> bool:
        """Hit NSE page to obtain fresh session cookies."""
        try:
            url = f"{self.BASE_URL}/get-quotes/equity"
            resp = self.session.get(
                url, params={"symbol": symbol}, timeout=config.request_timeout
            )
            resp.raise_for_status()
            self._cookie_expiry = datetime.now() + timedelta(seconds=_COOKIE_TTL_SECONDS)
            self._request_count = 0
            return True
        except Exception as e:
            print(f"  NSE cookie refresh failed: {e}")
            return False

    def _ensure_fresh_cookies(self, symbol: str = "TCS") -> None:
        """Refresh cookies if expired or request count exceeded."""
        now = datetime.now()
        expired = (
            self._cookie_expiry is None
            or now >= self._cookie_expiry
            or self._request_count >= _MAX_REQUESTS_PER_SESSION
        )
        if expired:
            self._refresh_cookies(symbol)

    def _get_json(self, url: str, params: dict, symbol: str = "TCS"):
        """Make a rate-limited, cookie-managed GET request returning JSON."""
        self._ensure_fresh_cookies(symbol)
        time.sleep(_NSE_DELAY)
        resp = self.session.get(url, params=params, timeout=config.request_timeout)
        self._request_count += 1

        # Retry once on auth failure with fresh cookies
        if resp.status_code in (401, 403):
            self._refresh_cookies(symbol)
            time.sleep(_NSE_DELAY)
            resp = self.session.get(url, params=params, timeout=config.request_timeout)
            self._request_count += 1

        resp.raise_for_status()
        return resp.json()

    def search_company(self, query: str) -> Optional[dict]:
        normalized = normalize_company_name(query)
        try:
            data = self._get_json(self.AUTOCOMPLETE_URL, {"q": normalized})
            symbols = data.get("symbols", [])
            if not symbols:
                # Retry with original query
                if normalized != query:
                    data = self._get_json(self.AUTOCOMPLETE_URL, {"q": query})
                    symbols = data.get("symbols", [])
            if not symbols:
                return None

            first = symbols[0]
            return {
                "name": first.get("symbol_info", query),
                "symbol": first["symbol"],
                "url": f"{self.BASE_URL}/get-quotes/equity?symbol={first['symbol']}",
                "source": self.source_name,
                "region": self.region.value,
            }
        except Exception as e:
            print(f"  NSE search failed for '{query}': {e}")
            return None

    def suggest_companies(self, query: str, limit: int = 8) -> List[dict]:
        try:
            data = self._get_json(self.AUTOCOMPLETE_URL, {"q": query})
            symbols = data.get("symbols", [])
            return [
                {
                    "name": s.get("symbol_info", s["symbol"]),
                    "source": self.source_name,
                    "region": self.region.value,
                }
                for s in symbols[:limit]
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

            symbol = company_info["symbol"]
            actual_name = company_info["name"]
            from_date, to_date = self._get_date_range(count)

            calls = []

            # Fetch corporate announcements
            try:
                announcements = self._get_json(
                    self.ANNOUNCEMENTS_URL,
                    {
                        "index": "equities",
                        "symbol": symbol,
                        "from_date": from_date,
                        "to_date": to_date,
                    },
                    symbol=symbol,
                )
                if isinstance(announcements, list):
                    for row in announcements:
                        call = self._parse_announcement(row, actual_name, flags)
                        if call:
                            calls.append(call)
            except Exception as e:
                print(f"  NSE announcements fetch failed for '{symbol}': {e}")

            # Fetch annual reports separately
            if include_annual_reports:
                try:
                    ar_data = self._get_json(
                        self.ANNUAL_REPORTS_URL,
                        {"index": "equities", "symbol": symbol},
                        symbol=symbol,
                    )
                    for item in (ar_data.get("data") or []):
                        file_url = item.get("fileName", "")
                        if not file_url:
                            continue
                        to_yr = item.get("toYr", "")
                        if to_yr:
                            fy_year = f"FY{str(to_yr)[-2:]}"
                        else:
                            continue
                        calls.append(EarningsCall(
                            company=actual_name,
                            quarter="FY",
                            year=fy_year,
                            doc_type="annual_report",
                            url=file_url,
                            source=self.source_name,
                            date=None,
                        ))
                except Exception as e:
                    print(f"  NSE annual reports fetch failed for '{symbol}': {e}")

            return self._limit_by_quarter(calls, count)

        except Exception as e:
            print(f"  NSE get_earnings_calls failed for '{company_name}': {e}")
            return []

    def _get_date_range(self, count: int) -> tuple:
        """Return (from_date, to_date) as DD-MM-YYYY strings."""
        to_date = datetime.now()
        days_back = count * 92 + 180
        from_date = to_date - timedelta(days=days_back)
        return from_date.strftime("%d-%m-%Y"), to_date.strftime("%d-%m-%Y")

    def _parse_announcement(self, row: dict, company_name: str, flags: dict) -> Optional[EarningsCall]:
        """Parse a single NSE announcement into an EarningsCall, or None if irrelevant."""
        file_url = row.get("attchmntFile", "")
        if not file_url:
            return None

        # Classify document type
        doc_type = self._classify_doc_type(row)
        if not doc_type:
            return None

        # Check if this doc_type is enabled
        flag_name = DOC_TYPE_FLAGS.get(doc_type)
        if flag_name and not flags.get(flag_name, True):
            return None

        # Extract quarter/year — try desc text first, then filing date
        desc = row.get("desc", "") or ""
        attchmnt_text = row.get("attchmntText", "") or ""
        quarter_info = _extract_quarter_from_text(desc) or _extract_quarter_from_text(attchmnt_text)

        if not quarter_info:
            filing_date = self._parse_date(row.get("an_dt") or row.get("sort_date", ""))
            if filing_date:
                quarter_info = _extract_quarter_from_date(filing_date)

        if not quarter_info:
            return None

        quarter, year = quarter_info
        filing_date = self._parse_date(row.get("an_dt") or row.get("sort_date", ""))

        return EarningsCall(
            company=company_name,
            quarter=quarter,
            year=year,
            doc_type=doc_type,
            url=file_url,
            source=self.source_name,
            date=filing_date,
        )

    def _classify_doc_type(self, row: dict) -> Optional[str]:
        """Classify an NSE announcement into a doc_type."""
        desc = (row.get("desc") or "").strip().lower()
        attchmnt_text = (row.get("attchmntText") or "").lower()

        # For "Outcome of Board Meeting" — check if it contains financial results
        if desc == "outcome of board meeting":
            if "financial result" in attchmnt_text:
                return "pnl"
            return "press_release"

        # Exact match on desc
        if desc in NSE_DOC_TYPE_MAP:
            return NSE_DOC_TYPE_MAP[desc]

        # Keyword match on desc + attachment text
        combined = desc + " " + attchmnt_text
        for keyword, dtype in NSE_DOC_KEYWORDS.items():
            if keyword in combined:
                return dtype

        # If desc mentions "result" at all, assume pnl
        if "result" in desc:
            return "pnl"

        return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse NSE date string."""
        if not date_str:
            return None
        for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except (ValueError, TypeError):
                continue
        return None

    def _limit_by_quarter(self, calls: List[EarningsCall], count: int) -> List[EarningsCall]:
        """Limit results to specified number of quarters."""
        by_quarter = defaultdict(list)
        for call in calls:
            by_quarter[(call.quarter, call.year)].append(call)

        def quarter_sort_key(q):
            quarter, year = q
            q_num = int(quarter[1]) if quarter.startswith("Q") else 0
            y_num = int(year[2:]) if len(year) >= 4 and year.startswith("FY") else 0
            return (-y_num, -q_num)

        sorted_quarters = sorted(by_quarter.keys(), key=quarter_sort_key)
        result = []
        for quarter_key in sorted_quarters[:count]:
            result.extend(by_quarter[quarter_key])
        return result


# Auto-register when module is imported
SourceRegistry.register(NSESource())
