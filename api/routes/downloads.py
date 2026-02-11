"""Download API endpoints."""

import os
import io
import zipfile
import asyncio
import aiohttp
from typing import List, Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.services import EarningsService
from core.models import EarningsCall
from sources.base import Region
from analysis.quarter_verify import verify_and_correct
from config import config


router = APIRouter(prefix="/api", tags=["downloads"])
service = EarningsService()


class DocumentResponse(BaseModel):
    """Earnings document info."""
    company: str
    quarter: str
    year: str
    doc_type: str
    url: str
    source: str
    filename: str


class DownloadRequest(BaseModel):
    """Download request body."""
    company: str  # Can be comma-separated for multiple companies
    region: Optional[str] = "india"
    count: int = 5
    include_transcripts: bool = True
    include_presentations: bool = True
    include_press_releases: bool = True


@router.get("/documents", response_model=List[DocumentResponse])
async def get_documents(
    company: str = Query(..., description="Company name(s), comma-separated for multiple"),
    region: Optional[str] = Query("india", description="Region (india, us, japan, korea, china)"),
    count: int = Query(8, ge=1, le=40, description="Number of quarters per company (max 40 = 10 years)"),
    types: Optional[str] = Query(
        "transcript,presentation,press_release",
        description="Document types (comma-separated)"
    )
):
    """
    Get available earnings documents for one or more companies.
    """
    region_enum = None
    if region:
        try:
            region_enum = Region(region.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid region: {region}")

    doc_types = [t.strip() for t in types.split(",")] if types else ["transcript"]

    # Support multiple companies (comma-separated)
    companies = [c.strip() for c in company.split(",") if c.strip()]

    all_documents = []
    for comp in companies:
        documents = service.get_earnings_documents(
            comp,
            region=region_enum,
            count=count,
            include_transcripts="transcript" in doc_types,
            include_presentations="presentation" in doc_types,
            include_press_releases="press_release" in doc_types
        )
        all_documents.extend(documents)

    return [
        DocumentResponse(
            company=doc.company,
            quarter=doc.quarter,
            year=doc.year,
            doc_type=doc.doc_type,
            url=doc.url,
            source=doc.source,
            filename=doc.get_filename()
        )
        for doc in all_documents
    ]


class VerifyRequest(BaseModel):
    """Request body for quarter verification."""
    documents: List[DocumentResponse]


class VerifiedDocument(BaseModel):
    """Document with verified quarter info."""
    company: str
    quarter: str
    year: str
    doc_type: str
    url: str
    source: str
    filename: str
    verified: bool = False
    was_corrected: bool = False
    original_quarter: Optional[str] = None
    original_year: Optional[str] = None


@router.post("/documents/verify", response_model=List[VerifiedDocument])
async def verify_quarters(request: VerifyRequest):
    """
    Verify quarter labels by reading the first 3 pages of each PDF.

    Downloads each document, checks for explicit quarter mentions in
    the content, and returns corrected labels where they differ.
    """
    async with aiohttp.ClientSession(
        headers={"User-Agent": config.user_agent}
    ) as session:
        tasks = []
        for doc in request.documents:
            call = EarningsCall(
                company=doc.company,
                quarter=doc.quarter,
                year=doc.year,
                doc_type=doc.doc_type,
                url=doc.url,
                source=doc.source,
            )
            tasks.append(fetch_file(session, doc.url, call))
        results = await asyncio.gather(*tasks)

    verified = []
    for doc, content in results:
        if content:
            corrected, was_corrected, was_verified = verify_and_correct(doc, content)
            verified.append(VerifiedDocument(
                company=corrected.company,
                quarter=corrected.quarter,
                year=corrected.year,
                doc_type=corrected.doc_type,
                url=corrected.url,
                source=corrected.source,
                filename=corrected.get_filename(),
                verified=was_verified,
                was_corrected=was_corrected,
                original_quarter=doc.quarter if was_corrected else None,
                original_year=doc.year if was_corrected else None,
            ))
        else:
            # Could not fetch PDF at all
            verified.append(VerifiedDocument(
                company=doc.company,
                quarter=doc.quarter,
                year=doc.year,
                doc_type=doc.doc_type,
                url=doc.url,
                source=doc.source,
                filename=doc.get_filename(),
                verified=False,
            ))

    return verified


async def fetch_file(session: aiohttp.ClientSession, url: str, doc: EarningsCall) -> tuple:
    """Fetch a single file and return (doc, content) or (doc, None) on error."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                content = await resp.read()
                return (doc, content)
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
    return (doc, None)


@router.post("/downloads/zip")
async def download_as_zip(request: DownloadRequest):
    """
    Download all earnings documents as a ZIP file.

    Fetches all documents and returns them as a downloadable ZIP.
    Supports multiple companies (comma-separated).
    """
    region_enum = None
    if request.region:
        try:
            region_enum = Region(request.region.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid region: {request.region}")

    # Support multiple companies (comma-separated)
    companies = [c.strip() for c in request.company.split(",") if c.strip()]

    all_documents = []
    for comp in companies:
        documents = service.get_earnings_documents(
            comp,
            region=region_enum,
            count=request.count,
            include_transcripts=request.include_transcripts,
            include_presentations=request.include_presentations,
            include_press_releases=request.include_press_releases
        )
        all_documents.extend(documents)

    if not all_documents:
        raise HTTPException(status_code=404, detail="No documents found for the specified companies")

    # Fetch all files concurrently
    async with aiohttp.ClientSession(
        headers={"User-Agent": config.user_agent}
    ) as session:
        tasks = [
            fetch_file(session, doc.url, doc)
            for doc in all_documents
        ]
        results = await asyncio.gather(*tasks)

    # Create ZIP in memory, verifying quarters from PDF content
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc, content in results:
            if content:
                corrected_doc, _, _ = verify_and_correct(doc, content)
                zf.writestr(corrected_doc.get_filename(), content)

    zip_buffer.seek(0)

    # Generate safe filename
    if len(companies) == 1:
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in companies[0])
        safe_name = safe_name.strip().replace(" ", "_")[:30]
    else:
        safe_name = f"{len(companies)}_companies"
    zip_filename = f"{safe_name}_earnings.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )
