# Earnings Call Transcript Downloader

Interactive CLI tool to download earnings call transcripts and investor presentations for Indian companies from Screener.in.

## Installation

```bash
cd ~/earnings_downloader
pip install -r requirements.txt
```

## Usage

```bash
python main.py
# or if alias is set up:
earnings
```

### Interactive Menu

```
Enter company name(s) (comma-separated for multiple)
Companies: Reliance Industries, TCS, HDFC Bank

Options:
  [1] Download transcripts only
  [2] Download transcripts + investor presentations
  [3] Change output directory (current: ./downloads)
  [4] Change transcript count (current: 4)
  [5] Exit
```

## Features

- **Checks company IR websites first**, then falls back to Screener.in
- Downloads 4 most recent quarterly earnings calls (configurable)
- Supports investor presentations
- Known IR pages for 25+ major Indian companies
- Organizes files by company in subdirectories
- Progress display with rich formatting
- Handles Indian financial year quarters:
  - Q1: Apr-Jun
  - Q2: Jul-Sep
  - Q3: Oct-Dec
  - Q4: Jan-Mar

## Output Structure

```
./downloads/
├── Reliance_Industries_Ltd/
│   ├── Reliance_Industries_Ltd_Q3FY26_transcript.pdf
│   ├── Reliance_Industries_Ltd_Q3FY26_presentation.pdf
│   ├── Reliance_Industries_Ltd_Q2FY26_transcript.pdf
│   └── ...
├── TCS_Ltd/
│   └── ...
└── HDFC_Bank_Ltd/
    └── ...
```

## Project Structure

```
earnings_downloader/
├── main.py           # Interactive CLI entry point
├── config.py         # Configuration settings
├── downloader.py     # Async download manager with retry logic
├── utils.py          # Helpers (naming, deduplication, quarter parsing)
├── requirements.txt  # Python dependencies
└── sources/
    ├── __init__.py
    └── screener.py   # Screener.in scraper
```

## Dependencies

- requests
- beautifulsoup4
- aiohttp
- rich

## Quick Access (Alias)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
alias earnings="cd ~/earnings_downloader && python3 main.py"
```

Then run `earnings` from anywhere.

## Data Sources (Priority Order)

1. **Company IR Websites** - Official investor relations pages (checked first)
2. **Screener.in** - Aggregates filings from BSE India (fallback)

Known IR page mappings exist for: Reliance, TCS, Infosys, HDFC Bank, ICICI Bank, Wipro, HCL Tech, Bharti Airtel, Maruti Suzuki, Motherson, Bajaj Finance, Kotak, Axis Bank, ITC, L&T, Sun Pharma, Titan, UltraTech, Nestle India, Power Grid, NTPC, ONGC, SBI, and more.
