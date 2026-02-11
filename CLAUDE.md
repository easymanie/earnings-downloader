# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the CLI
python cli/app.py

# Run the web server
uvicorn api.app:app --reload --port 8000

# Install dependencies
pip install -r requirements.txt
```

No tests exist yet. No build step required.

## Architecture

This tool downloads earnings documents (transcripts, presentations, press releases/factsheets) for companies worldwide.

### Project Structure

```
earnings_downloader/
├── core/                    # Business logic (shared)
│   ├── models.py           # Pydantic models (EarningsCall, CompanyAnalysis, etc.)
│   ├── services/
│   │   ├── earnings.py     # EarningsService - download business logic
│   │   └── analysis.py     # AnalysisService - analysis business logic
│   └── storage/
│       ├── database.py     # SQLite setup and wrapper
│       └── repositories.py # Data access (AnalysisRepo, IndustryRepo, etc.)
├── analysis/                # Earnings analysis pipeline
│   ├── extractor.py        # PDF text extraction (PyMuPDF + pdfplumber)
│   ├── pipeline.py         # Analysis orchestrator (extract -> LLM -> store)
│   ├── comparator.py       # QoQ/YoY comparison logic
│   ├── llm/                # Multi-LLM client abstraction
│   │   ├── base.py         # BaseLLMClient ABC
│   │   ├── claude.py       # Anthropic Claude
│   │   ├── openai_client.py # OpenAI
│   │   └── gemini.py       # Google Gemini
│   └── prompts/            # Prompt templates
│       ├── metrics.py      # Financial metric extraction
│       └── themes.py       # Theme identification + industry narrative
├── sources/                 # Data sources by region
│   ├── base.py             # BaseSource ABC, Region enum, FiscalYearType enum
│   ├── registry.py         # SourceRegistry for managing sources
│   ├── india/              # Screener.in (primary) + Company IR pages (secondary)
│   ├── us/                 # SEC EDGAR
│   ├── japan/              # J-Quants/TDnet
│   ├── korea/              # DART
│   └── china/              # CNINFO
├── api/                     # FastAPI backend
│   ├── app.py              # Main app, mounts static files
│   └── routes/
│       ├── companies.py    # Search and regions endpoints
│       ├── downloads.py    # Documents list and ZIP download
│       └── analysis.py     # Analysis + industry endpoints
├── cli/                     # CLI interface
│   └── app.py              # Interactive CLI
├── web/                     # Frontend
│   ├── index.html          # Download page
│   ├── analysis.html       # Company analysis page
│   ├── industry.html       # Industry analysis page
│   ├── app.js              # Download page JS
│   ├── analysis.js         # Analysis page JS
│   ├── industry.js         # Industry page JS
│   └── style.css           # Styling
├── data/
│   ├── industries.json     # Seed data for industry->company mappings
│   └── earnings.db         # SQLite database (gitignored)
├── config.py               # Configuration (API keys, LLM settings, timeouts)
├── downloader.py           # Async download manager
└── utils.py                # Backwards-compatible exports
```

### Key Design Decisions

- **Pluggable sources**: Each region has source(s) extending `BaseSource`. Auto-registration via `SourceRegistry`.
- **Service layer**: `EarningsService` provides shared business logic for both CLI and API.
- **Fiscal year handling**: India/Japan use Apr-Mar FY; US/Korea/China use calendar year.
- **Fuzzy matching**: Uses `rapidfuzz` library for company name matching with configurable threshold.
- **Multi-company support**: API accepts comma-separated company names.

### Source Priority (for deduplication)

Lower number = higher priority. When the same document is found from multiple sources, the highest priority source is kept:

```
Priority 0 (Official filings): bse, nse, edgar, tdnet, dart, cninfo
Priority 1 (Aggregators):      screener, trendlyne, tijori
Priority 2 (Company sites):    company_ir
```

For India specifically:
1. NSE/BSE exchange filings (via Screener links) - transcripts, presentations
2. Screener.in - discovers documents for any Indian company
3. Company IR websites - factsheets, additional materials not on exchanges

### Adding New Sources

1. Create `sources/{region}/{source_name}.py`
2. Extend `BaseSource` with required attributes:
   - `region`: Region enum value
   - `fiscal_year_type`: FiscalYearType.INDIAN or FiscalYearType.CALENDAR
   - `source_name`: String identifier
   - `priority`: Integer (lower = higher priority for deduplication)
3. Implement `search_company()` and `get_earnings_calls()`
4. Call `SourceRegistry.register(YourSource())` at module level
5. Import in `sources/{region}/__init__.py`

### API Endpoints

**Downloads:**
- `GET /api/regions` - List available regions with their sources
- `GET /api/companies/search?q=&region=` - Search companies by name
- `GET /api/documents?company=&region=&count=&types=` - Get available documents
- `POST /api/downloads/zip` - Download all documents as ZIP file

**Analysis:**
- `POST /api/analysis/analyze` - Trigger analysis for companies (body: `{companies, quarter, year, llm_provider}`)
- `GET /api/analysis/results/{company}?quarter=&year=` - Get stored analysis
- `GET /api/analysis/compare/{company}?quarter=&year=&type=qoq|yoy` - Quarter comparison
- `GET /api/analysis/industries` - List all industries with companies
- `POST /api/analysis/industries/{name}/analyze` - Run industry-level analysis
- `PUT /api/analysis/industries/{name}/companies` - Update industry company list
- `POST /api/analysis/industries/custom` - Create custom industry

### Environment Variables

```bash
# East Asian sources
DART_API_KEY=your_dart_key      # Korea DART API
TDNET_API_ID=your_id            # Japan J-Quants API
TDNET_API_PASSWORD=your_pass    # Japan J-Quants API

# LLM Configuration (for analysis features)
LLM_PROVIDER=claude             # claude, openai, or gemini
ANTHROPIC_API_KEY=              # For Claude
OPENAI_API_KEY=                 # For OpenAI
GOOGLE_API_KEY=                 # For Gemini
```

### Analysis Pipeline

The analysis pipeline (in `analysis/`) works as follows:
1. **PDF Extraction**: Extract text from downloaded PDFs using PyMuPDF (transcripts) or pdfplumber (presentations/press releases with tables)
2. **LLM Analysis**: Send extracted text to configured LLM for metric extraction and theme identification
3. **Storage**: Results cached in SQLite (`data/earnings.db`) for instant retrieval
4. **Comparison**: Pure Python QoQ/YoY comparison with configurable materiality thresholds
5. **Industry Aggregation**: Cross-company theme aggregation and narrative generation via LLM

All prompts are India-specific (INR Cr, FY convention). The LLM client abstraction supports Claude, OpenAI, and Gemini with a single `BaseLLMClient` interface.

### Deduplication Logic (core/models.py)

The `deduplicate_calls()` function handles two levels:
1. **URL deduplication**: Exact same document URL keeps highest priority source
2. **Semantic deduplication**: Same (company, quarter, year, doc_type) keeps highest priority source

Company names are normalized before comparison using `normalize_company_name()`.

### Press Release / Factsheet Filtering

For Indian sources, "press_release" doc_type specifically targets:
- Official factsheets from company IR pages
- BSE/NSE filed documents with keywords: "fact sheet", "factsheet", "snapshot", "highlights"
- Only PDF documents from official sources are included
