// Earnings Downloader Frontend

const API_BASE = '';

let currentDocuments = [];

// DOM Elements
const searchForm = document.getElementById('search-form');
const resultsSection = document.getElementById('results');
const resultsBody = document.getElementById('results-body');
const loadingEl = document.getElementById('loading');
const noResultsEl = document.getElementById('no-results');
const downloadAllBtn = document.getElementById('download-all-btn');
const downloadStatus = document.getElementById('download-status');
const statusMessage = document.getElementById('status-message');
const searchBtn = document.getElementById('search-btn');

// Autocomplete elements
const companyInput = document.getElementById('company');
const autocompleteDropdown = document.getElementById('autocomplete-dropdown');
let autocompleteTimer = null;
let activeIndex = -1;

// Event Listeners
searchForm.addEventListener('submit', handleSearch);
downloadAllBtn.addEventListener('click', handleDownloadAll);

// --- Autocomplete ---

companyInput.addEventListener('input', () => {
    clearTimeout(autocompleteTimer);
    const raw = companyInput.value;
    const lastComma = raw.lastIndexOf(',');
    const currentToken = (lastComma >= 0 ? raw.slice(lastComma + 1) : raw).trim();

    if (currentToken.length < 2) {
        closeAutocomplete();
        return;
    }

    autocompleteTimer = setTimeout(() => fetchSuggestions(currentToken), 300);
});

companyInput.addEventListener('keydown', (e) => {
    if (autocompleteDropdown.classList.contains('hidden')) return;

    const items = autocompleteDropdown.querySelectorAll('.autocomplete-item');
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, items.length - 1);
        highlightItem(items);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        highlightItem(items);
    } else if (e.key === 'Enter' && activeIndex >= 0) {
        e.preventDefault();
        selectSuggestion(items[activeIndex].dataset.name);
    } else if (e.key === 'Escape') {
        closeAutocomplete();
    }
});

document.addEventListener('click', (e) => {
    if (!e.target.closest('.autocomplete-wrapper')) {
        closeAutocomplete();
    }
});

async function fetchSuggestions(query) {
    const region = document.getElementById('region').value;
    try {
        const params = new URLSearchParams({ q: query, region, limit: '8' });
        const resp = await fetch(`${API_BASE}/api/companies/suggest?${params}`);
        if (!resp.ok) return;
        const suggestions = await resp.json();
        renderSuggestions(suggestions);
    } catch (err) {
        console.error('Suggest error:', err);
    }
}

function renderSuggestions(suggestions) {
    if (suggestions.length === 0) {
        closeAutocomplete();
        return;
    }

    activeIndex = -1;
    autocompleteDropdown.innerHTML = suggestions.map((s, i) =>
        `<div class="autocomplete-item" data-name="${escapeHtml(s.name)}">${escapeHtml(s.name)}<span class="source-tag">${escapeHtml(s.source)}</span></div>`
    ).join('');
    autocompleteDropdown.classList.remove('hidden');

    autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(item => {
        item.addEventListener('mousedown', (e) => {
            e.preventDefault();
            selectSuggestion(item.dataset.name);
        });
    });
}

function selectSuggestion(name) {
    const raw = companyInput.value;
    const lastComma = raw.lastIndexOf(',');
    if (lastComma >= 0) {
        companyInput.value = raw.slice(0, lastComma + 1) + ' ' + name;
    } else {
        companyInput.value = name;
    }
    closeAutocomplete();
    companyInput.focus();
}

function highlightItem(items) {
    items.forEach((item, i) => {
        item.classList.toggle('active', i === activeIndex);
    });
    if (activeIndex >= 0 && items[activeIndex]) {
        items[activeIndex].scrollIntoView({ block: 'nearest' });
    }
}

function closeAutocomplete() {
    autocompleteDropdown.classList.add('hidden');
    autocompleteDropdown.innerHTML = '';
    activeIndex = -1;
}

async function handleSearch(e) {
    e.preventDefault();

    const company = document.getElementById('company').value.trim();
    const region = document.getElementById('region').value;
    const count = document.getElementById('count').value;

    const typeCheckboxes = document.querySelectorAll('input[name="types"]:checked');
    const types = Array.from(typeCheckboxes).map(cb => cb.value).join(',');

    if (!company) {
        alert('Please enter a company name');
        return;
    }

    if (!types) {
        alert('Please select at least one document type');
        return;
    }

    // Show loading state
    resultsSection.classList.remove('hidden');
    loadingEl.classList.remove('hidden');
    noResultsEl.classList.add('hidden');
    resultsBody.innerHTML = '';
    downloadAllBtn.classList.add('hidden');
    downloadStatus.classList.add('hidden');
    searchBtn.disabled = true;
    searchBtn.textContent = 'Searching...';

    try {
        const params = new URLSearchParams({
            company,
            region,
            count,
            types
        });

        const response = await fetch(`${API_BASE}/api/documents?${params}`);

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Search failed');
        }

        const documents = await response.json();
        currentDocuments = documents;

        displayResults(documents);

    } catch (error) {
        console.error('Search error:', error);
        noResultsEl.textContent = `Error: ${error.message}`;
        noResultsEl.classList.remove('hidden');
    } finally {
        loadingEl.classList.add('hidden');
        searchBtn.disabled = false;
        searchBtn.textContent = 'Search Documents';
    }
}

function displayResults(documents) {
    resultsBody.innerHTML = '';

    if (documents.length === 0) {
        noResultsEl.textContent = 'No documents found for this company.';
        noResultsEl.classList.remove('hidden');
        downloadAllBtn.classList.add('hidden');
        return;
    }

    noResultsEl.classList.add('hidden');

    documents.forEach(doc => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${escapeHtml(doc.company.substring(0, 30))}</td>
            <td>${escapeHtml(doc.quarter)} ${escapeHtml(doc.year)}</td>
            <td>${formatDocType(doc.doc_type)}</td>
            <td>${escapeHtml(doc.source)}</td>
            <td>
                <a href="${escapeHtml(doc.url)}" target="_blank" class="btn-download" style="display:inline-block;text-decoration:none;color:white;">
                    Download
                </a>
            </td>
        `;
        resultsBody.appendChild(row);
    });

    downloadAllBtn.classList.remove('hidden');
    downloadAllBtn.textContent = `Download All (${documents.length} files)`;
}

async function handleDownloadAll() {
    if (currentDocuments.length === 0) return;

    const company = document.getElementById('company').value.trim();
    const region = document.getElementById('region').value;

    const typeCheckboxes = document.querySelectorAll('input[name="types"]:checked');
    const types = Array.from(typeCheckboxes).map(cb => cb.value);

    downloadAllBtn.disabled = true;
    downloadAllBtn.textContent = 'Preparing ZIP...';
    downloadStatus.classList.remove('hidden');
    statusMessage.textContent = 'Fetching documents and creating ZIP file...';

    try {
        const response = await fetch(`${API_BASE}/api/downloads/zip`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                company,
                region,
                count: parseInt(document.getElementById('count').value),
                include_transcripts: types.includes('transcript'),
                include_presentations: types.includes('presentation'),
                include_press_releases: types.includes('press_release'),
                include_balance_sheets: types.includes('balance_sheet'),
                include_pnl: types.includes('pnl'),
                include_cash_flow: types.includes('cash_flow'),
                include_annual_reports: types.includes('annual_report')
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            let errorMessage = 'Download failed';
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage = errorJson.detail || errorMessage;
            } catch (e) {
                errorMessage = errorText || errorMessage;
            }
            throw new Error(errorMessage);
        }

        // Get the blob and trigger download
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;

        // Get filename from Content-Disposition header or use default
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = `${company.replace(/[^a-zA-Z0-9]/g, '_')}_earnings.zip`;
        if (contentDisposition) {
            const match = contentDisposition.match(/filename=(.+)/);
            if (match) {
                filename = match[1].replace(/"/g, '');
            }
        }

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();

        statusMessage.textContent = `Downloaded ${currentDocuments.length} documents as ZIP!`;

    } catch (error) {
        console.error('Download error:', error);
        statusMessage.textContent = `Error: ${error.message}`;
    } finally {
        downloadAllBtn.disabled = false;
        downloadAllBtn.textContent = `Download All (${currentDocuments.length} files)`;
    }
}

function formatDocType(docType) {
    const labels = {
        'transcript': 'Transcript',
        'presentation': 'Presentation',
        'press_release': 'Press Release',
        'balance_sheet': 'Balance Sheet',
        'pnl': 'P&L Statement',
        'cash_flow': 'Cash Flow',
        'annual_report': 'Annual Report'
    };
    return labels[docType] || docType;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Load available regions on page load
async function loadRegions() {
    try {
        const response = await fetch(`${API_BASE}/api/companies/regions`);
        if (response.ok) {
            const regions = await response.json();
            const regionSelect = document.getElementById('region');

            // Update options based on available regions
            regionSelect.innerHTML = '';
            regions.forEach(region => {
                const option = document.createElement('option');
                option.value = region.id;
                option.textContent = `${region.name} (${region.fiscal_year} FY)`;
                regionSelect.appendChild(option);
            });

            // If no regions, show default
            if (regions.length === 0) {
                regionSelect.innerHTML = '<option value="india">India</option>';
            }
        }
    } catch (error) {
        console.log('Could not load regions, using defaults');
    }
}

// Initialize
loadRegions();
