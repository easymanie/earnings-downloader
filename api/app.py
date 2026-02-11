"""FastAPI application for earnings downloader."""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routes import companies_router, downloads_router, analysis_router


# Get the project root directory
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")
DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")


app = FastAPI(
    title="Earnings Downloader API",
    description="Download earnings documents (transcripts, presentations, press releases) for companies worldwide",
    version="1.0.0"
)

# Include API routers
app.include_router(companies_router)
app.include_router(downloads_router)
app.include_router(analysis_router)


# Serve static files for frontend
if os.path.exists(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
async def root():
    """Serve the main page."""
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "Earnings Downloader API",
        "docs": "/docs",
        "endpoints": {
            "search": "/api/companies/search?q=company_name",
            "regions": "/api/companies/regions",
            "documents": "/api/documents?company=company_name",
            "download": "POST /api/downloads"
        }
    }


@app.get("/analysis")
async def analysis_page():
    """Serve the analysis page."""
    page_path = os.path.join(WEB_DIR, "analysis.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Analysis page not found"}


@app.get("/industry")
async def industry_page():
    """Serve the industry analysis page."""
    page_path = os.path.join(WEB_DIR, "industry.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Industry page not found"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
