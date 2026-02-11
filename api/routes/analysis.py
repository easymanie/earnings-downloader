"""API routes for earnings analysis."""

from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from core.services.analysis import AnalysisService


router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# Lazy-init service (created on first request)
_service: Optional[AnalysisService] = None


def _get_service() -> AnalysisService:
    global _service
    if _service is None:
        _service = AnalysisService()
    return _service


# --- Request/Response models ---

class AnalyzeRequest(BaseModel):
    company: str
    quarter: str
    year: str
    lookback_quarters: int = 4
    force: bool = False
    llm_provider: Optional[str] = None


class IndustryAnalyzeRequest(BaseModel):
    quarter: str
    year: str
    force: bool = False
    llm_provider: Optional[str] = None


class UpdateCompaniesRequest(BaseModel):
    companies: List[str]


class CreateIndustryRequest(BaseModel):
    name: str
    companies: List[str]


# --- Analysis endpoints ---

@router.post("/analyze")
async def analyze_company(request: AnalyzeRequest):
    """Analyze a company's quarter with preceding quarters for trend context."""
    service = _get_service()
    try:
        result = service.analyze_with_context(
            company=request.company,
            quarter=request.quarter,
            year=request.year,
            lookback=request.lookback_quarters,
            force=request.force,
            provider=request.llm_provider,
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results/{company}")
async def get_analysis_results(
    company: str,
    quarter: Optional[str] = None,
    year: Optional[str] = None,
):
    """Get stored analysis results for a company."""
    service = _get_service()
    result = service.get_analysis(company, quarter, year)

    if result is None:
        raise HTTPException(status_code=404, detail=f"No analysis found for {company}")

    if isinstance(result, list):
        return {"analyses": [r.model_dump() for r in result]}
    return result.model_dump()


@router.get("/compare/{company}")
async def compare_quarters(
    company: str,
    quarter: str,
    year: str,
    type: str = "qoq",
):
    """Get quarter-over-quarter or year-over-year comparison."""
    if type not in ("qoq", "yoy"):
        raise HTTPException(status_code=400, detail="type must be 'qoq' or 'yoy'")

    service = _get_service()
    result = service.compare_quarters(company, quarter, year, type)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot compare: need analyses for both current and previous quarter",
        )
    return result.model_dump()


# --- Industry endpoints ---

@router.get("/industries")
async def list_industries():
    """List all industries with their companies."""
    service = _get_service()
    return service.get_industries()


@router.post("/industries/{industry}/analyze")
async def analyze_industry(industry: str, request: IndustryAnalyzeRequest):
    """Run industry-level analysis."""
    service = _get_service()
    try:
        result = service.analyze_industry(
            industry=industry,
            quarter=request.quarter,
            year=request.year,
            force=request.force,
            provider=request.llm_provider,
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industries/{industry}")
async def get_industry_analysis(industry: str, quarter: str, year: str):
    """Get stored industry analysis."""
    service = _get_service()
    result = service.get_industry_analysis(industry, quarter, year)
    if not result:
        raise HTTPException(status_code=404, detail=f"No analysis found for {industry}")
    return result.model_dump()


@router.put("/industries/{industry}/companies")
async def update_industry_companies(industry: str, request: UpdateCompaniesRequest):
    """Update the company list for an industry."""
    service = _get_service()
    service.update_industry_companies(industry, request.companies)
    return {"status": "updated", "industry": industry, "companies": request.companies}


@router.post("/industries/custom")
async def create_custom_industry(request: CreateIndustryRequest):
    """Create a new custom industry grouping."""
    service = _get_service()
    service.create_industry(request.name, request.companies)
    return {"status": "created", "industry": request.name, "companies": request.companies}
