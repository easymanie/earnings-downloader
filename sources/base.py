"""Base class for earnings document sources."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Any


class Region(Enum):
    """Supported regions for earnings documents."""
    INDIA = "india"
    US = "us"
    JAPAN = "japan"
    KOREA = "korea"
    CHINA = "china"


class FiscalYearType(Enum):
    """Fiscal year conventions."""
    CALENDAR = "calendar"  # Jan-Dec (US, Korea, China)
    INDIAN = "indian"      # Apr-Mar (India)
    JAPANESE = "japanese"  # Apr-Mar (Japan, same as Indian)


class BaseSource(ABC):
    """Abstract base class for all earnings document sources."""

    # Subclasses must define these
    region: Region
    fiscal_year_type: FiscalYearType
    source_name: str
    priority: int  # Lower = higher priority for deduplication

    @abstractmethod
    def search_company(self, query: str) -> Optional[dict]:
        """
        Search for a company by name.

        Args:
            query: Company name or search term

        Returns:
            Dict with company info (name, url, ticker, etc.) or None if not found
        """
        pass

    @abstractmethod
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
    ) -> List[Any]:  # Returns List[EarningsCall] but avoiding circular import
        """
        Get earnings documents for a company.

        Args:
            company_name: Name of the company
            count: Number of quarters to fetch
            include_transcripts: Include earnings call transcripts
            include_presentations: Include investor presentations
            include_press_releases: Include press releases/fact sheets
            include_balance_sheets: Include balance sheet documents
            include_pnl: Include P&L / income statement documents
            include_cash_flow: Include cash flow statement documents
            include_annual_reports: Include annual reports (contain all financial statements)

        Returns:
            List of EarningsCall objects
        """
        pass
