"""Company search API endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from core.services import EarningsService
from sources.base import Region


router = APIRouter(prefix="/api/companies", tags=["companies"])
service = EarningsService()


class CompanySearchResult(BaseModel):
    """Company search result."""
    name: str
    url: str
    source: str
    region: str


class RegionInfo(BaseModel):
    """Region information."""
    id: str
    name: str
    fiscal_year: str
    sources: List[str]


@router.get("/search", response_model=List[CompanySearchResult])
async def search_companies(
    q: str = Query(..., min_length=1, description="Company name to search"),
    region: Optional[str] = Query(None, description="Region to search in (india, us, japan, korea, china)")
):
    """
    Search for companies by name.

    Returns list of matching companies with their IR page URLs and sources.
    """
    region_enum = None
    if region:
        try:
            region_enum = Region(region.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid region: {region}")

    results = service.search_company(q, region=region_enum)
    return results


class CompanySuggestion(BaseModel):
    """Company autocomplete suggestion."""
    name: str
    source: str
    region: str
    alias: Optional[str] = None


@router.get("/suggest", response_model=List[CompanySuggestion])
async def suggest_companies(
    q: str = Query(..., min_length=2, description="Partial company name"),
    region: Optional[str] = Query(None, description="Region to search in"),
    limit: int = Query(8, ge=1, le=20, description="Max suggestions")
):
    """Return company name suggestions for autocomplete."""
    region_enum = None
    if region:
        try:
            region_enum = Region(region.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid region: {region}")

    return service.suggest_companies(q, region=region_enum, limit=limit)


@router.get("/regions", response_model=List[RegionInfo])
async def list_regions():
    """
    List all available regions with their sources.
    """
    return service.get_available_regions()
