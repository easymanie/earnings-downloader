"""Data sources for earnings documents."""

from .base import BaseSource, Region, FiscalYearType
from .registry import SourceRegistry

# Import regional sources (auto-registers them)
from .india import BSESource, NSESource, ScreenerSource, CompanyIRSource
from .us import EdgarSource
from .japan import TdnetSource
from .korea import DartSource
from .china import CninfoSource

__all__ = [
    "BaseSource",
    "Region",
    "FiscalYearType",
    "SourceRegistry",
    "BSESource",
    "NSESource",
    "ScreenerSource",
    "CompanyIRSource",
    "EdgarSource",
    "TdnetSource",
    "DartSource",
    "CninfoSource",
]
