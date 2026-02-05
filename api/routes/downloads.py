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
    company: str
    region: Optional[str] = "india"
    count: int = 5
    include_transcripts: bool = True
    include_presentations: bool = True
    include_press_releases: bool = True


@router.get("/documents", response_model=List[DocumentResponse])
async def get_documents(
    company: str = Query(..., description="Company name"),
    region: Optional[str] = Query("india", description="Region (india, us, japan, korea, china)"),
    count: int = Query(5, ge=1, le=20, description="Number of quarters"),
    types: Optional[str] = Query(
        "transcript,presentation,press_release",
        description="Document types (comma-separated)"
    )
):
    """
    Get available earnings documents for a company.
    """
    region_enum = None
    if region:
        try:
            region_enum = Region(region.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid region: {region}")

    doc_types = [t.strip() for t in types.split(",")] if types else ["transcript"]

    documents = service.get_earnings_documents(
        company,
        region=region_enum,
        count=count,
        include_transcripts="transcript" in doc_types,
        include_presentations="presentation" in doc_types,
        include_press_releases="press_release" in doc_types
    )

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
        for doc in documents
    ]


async def fetch_file(session: aiohttp.ClientSession, url: str, filename: str) -> tuple:
    """Fetch a single file and return (filename, content) or (filename, None) on error."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                content = await resp.read()
                return (filename, content)
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
    return (filename, None)


@router.post("/downloads/zip")
async def download_as_zip(request: DownloadRequest):
    """
    Download all earnings documents as a ZIP file.

    Fetches all documents and returns them as a downloadable ZIP.
    """
    region_enum = None
    if request.region:
        try:
            region_enum = Region(request.region.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid region: {request.region}")

    documents = service.get_earnings_documents(
        request.company,
        region=region_enum,
        count=request.count,
        include_transcripts=request.include_transcripts,
        include_presentations=request.include_presentations,
        include_press_releases=request.include_press_releases
    )

    if not documents:
        raise HTTPException(status_code=404, detail="No documents found for this company")

    # Fetch all files concurrently
    async with aiohttp.ClientSession(
        headers={"User-Agent": config.user_agent}
    ) as session:
        tasks = [
            fetch_file(session, doc.url, doc.get_filename())
            for doc in documents
        ]
        results = await asyncio.gather(*tasks)

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, content in results:
            if content:
                zf.writestr(filename, content)

    zip_buffer.seek(0)

    # Generate safe filename
    safe_company = "".join(c if c.isalnum() or c in " -_" else "_" for c in request.company)
    safe_company = safe_company.strip().replace(" ", "_")[:30]
    zip_filename = f"{safe_company}_earnings.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )
