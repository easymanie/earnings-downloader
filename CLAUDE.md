# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the web server
uvicorn api.app:app --reload --port 8000

# Run the CLI
python3 cli/app.py

# Install dependencies
pip install -r requirements.txt
```

No tests exist yet. No build step required. Deployed to Railway via `git push` (auto-deploys from main).

## Architecture

Downloads and analyzes quarterly earnings documents (transcripts, presentations, press releases, balance sheets, P&L statements, cash flow statements, annual reports) for companies worldwide, with a focus on Indian markets.

### Key Design Decisions

- **Pluggable sources**: Each region has source(s) extending `BaseSource` (`sources/base.py`). Auto-registration via `SourceRegistry`.
- **Service layer**: `EarningsService` and `AnalysisService` in `core/services/` provide shared business logic for both CLI and API.
- **Multi-LLM support**: Factory pattern in `analysis/llm/__init__.py` — `get_llm_client(provider)` returns a `BaseLLMClient`. Supports Claude, OpenAI, Gemini, Ollama (local), and OpenRouter (free models via OpenAI-compatible API).
- **OpenRouter specifics**: Reuses `OpenAILLMClient` with custom `base_url` and `json_mode=False` (free models don't support `response_format: json_object`). Default model: `nvidia/nemotron-3-nano-30b-a3b:free`.
- **Company aliases**: `data/company_aliases.json` maps brand/colloquial names (e.g., "Mamaearth" → "Honasa Consumer", "PayTM" → "One 97 Communications") to official listed names. Resolved at service level in `EarningsService._resolve_alias()`.
- **Fiscal year handling**: India/Japan use Apr-Mar FY; US/Korea/China use calendar year.
- **Fuzzy matching**: Uses `rapidfuzz` library for company name matching.

### Indian Quarter Mapping — Critical Domain Rule

Months on Screener.in and company IR pages are **release dates**, NOT quarter-membership months. Results are released ~1-2 months after quarter end:

```
Release months Jan-May → Q4 results
Release months Jun-Aug → Q1 results
Release months Sep-Nov → Q2 results
Release month Dec      → Q3 results
```

Never treat Indian source months as "which quarter contains this month" — always map to the prior quarter. This mapping exists in both `sources/india/screener.py` and `sources/india/company_ir.py`.

### Analysis Pipeline

1. **PDF Extraction** (`analysis/extractor.py`): PyMuPDF for transcripts, pdfplumber for presentations/tables
2. **LLM Analysis** (`analysis/pipeline.py`): Two-pass — `_extract_metrics()` then `_extract_themes()` per quarter
3. **Multi-Quarter Synthesis** (`analyze_multi_quarter()`): Analyzes N quarters, then runs trend prompt for longitudinal context (metric trends, theme evolution, narrative shifts, consistency assessment)
4. **Storage**: Results cached in SQLite (`data/earnings.db`) via repositories in `core/storage/`
5. **Comparison** (`analysis/comparator.py`): Pure Python QoQ/YoY with configurable materiality thresholds
6. **Industry Aggregation**: Cross-company theme aggregation and narrative generation

All prompts are India-specific (INR Cr, FY convention). Free/smaller LLMs may return malformed JSON — the pipeline has try/except guards around all Pydantic model construction.

### Source Priority (for deduplication)

```
Priority 0 (Official filings): bse, nse, edgar, tdnet, dart, cninfo
Priority 1 (Aggregators):      screener, trendlyne, tijori
Priority 2 (Company sites):    company_ir
```

### API Endpoints

**Companies:**
- `GET /api/companies/search?q=&region=` — Search companies by name
- `GET /api/companies/suggest?q=&region=&limit=` — Autocomplete suggestions (min 2 chars, returns alias info)
- `GET /api/regions` — List available regions

**Downloads:**
- `GET /api/documents?company=&region=&count=&types=` — Get available documents
- `POST /api/downloads/zip` — Download all documents as ZIP file

**Analysis:**
- `POST /api/analysis/analyze` — Analyze company (body: `{company, quarter, year, lookback_quarters, llm_provider, force}`)
- `GET /api/analysis/results/{company}?quarter=&year=` — Get stored analysis
- `GET /api/analysis/compare/{company}?quarter=&year=&type=qoq|yoy` — Quarter comparison
- `GET /api/analysis/industries` — List all industries
- `POST /api/analysis/industries/{name}/analyze` — Run industry-level analysis
- `PUT /api/analysis/industries/{name}/companies` — Update industry company list
- `POST /api/analysis/industries/custom` — Create custom industry

### Environment Variables

```bash
# LLM providers (set the one you use)
LLM_PROVIDER=openrouter          # claude, openai, gemini, ollama, openrouter
OPENROUTER_API_KEY=              # For OpenRouter (free models available)
ANTHROPIC_API_KEY=               # For Claude
OPENAI_API_KEY=                  # For OpenAI
GOOGLE_API_KEY=                  # For Gemini
OLLAMA_MODEL=llama3.1:8b         # For local Ollama
OLLAMA_URL=http://localhost:11434

# Optional: override default models
OPENROUTER_MODEL=nvidia/nemotron-3-nano-30b-a3b:free
CLAUDE_MODEL=claude-sonnet-4-20250514
OPENAI_MODEL=gpt-4o
GEMINI_MODEL=gemini-2.0-flash

# East Asian sources
DART_API_KEY=                    # Korea DART API
TDNET_API_ID=                    # Japan J-Quants API
TDNET_API_PASSWORD=              # Japan J-Quants API
```

### Adding New Sources

1. Create `sources/{region}/{source_name}.py`
2. Extend `BaseSource` with: `region`, `fiscal_year_type`, `source_name`, `priority`
3. Implement `search_company()`, `get_earnings_calls()`, optionally `suggest_companies()`
4. Call `SourceRegistry.register(YourSource())` at module level
5. Import in `sources/{region}/__init__.py`

### Deployment

Hosted on Railway. Config in `railway.json` and `Procfile`. Auto-deploys on push to main.
