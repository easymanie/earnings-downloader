// Industry Analysis Frontend

const API_BASE = '';

const industrySelect = document.getElementById('industry');
const analyzeBtn = document.getElementById('analyze-btn');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');
const companyChips = document.getElementById('company-chips');

let industries = [];

// Load industries on page load
loadIndustries();

analyzeBtn.addEventListener('click', handleAnalyze);
industrySelect.addEventListener('change', updateCompanyChips);

async function loadIndustries() {
    try {
        const response = await fetch(`${API_BASE}/api/analysis/industries`);
        if (!response.ok) throw new Error('Failed to load industries');
        industries = await response.json();

        industrySelect.innerHTML = '';
        industries.forEach(ind => {
            const option = document.createElement('option');
            option.value = ind.industry;
            option.textContent = `${ind.industry} (${ind.companies.length} companies)`;
            industrySelect.appendChild(option);
        });

        if (industries.length > 0) {
            updateCompanyChips();
        }
    } catch (err) {
        industrySelect.innerHTML = '<option value="">Could not load industries</option>';
    }
}

function updateCompanyChips() {
    const selected = industrySelect.value;
    const industry = industries.find(i => i.industry === selected);
    companyChips.innerHTML = '';

    if (industry) {
        industry.companies.forEach(company => {
            const chip = document.createElement('span');
            chip.className = 'chip';
            chip.textContent = company;
            companyChips.appendChild(chip);
        });
    }
}

async function handleAnalyze() {
    const industry = industrySelect.value;
    const quarter = document.getElementById('quarter').value;
    const year = document.getElementById('year').value;
    const llm = document.getElementById('llm').value;

    if (!industry) return;

    showStatus('loading', `Analyzing ${industry} for ${quarter} ${year}... This may take several minutes for multiple companies.`);
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing...';
    resultsEl.classList.add('hidden');

    try {
        const response = await fetch(`${API_BASE}/api/analysis/industries/${encodeURIComponent(industry)}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ quarter, year, llm_provider: llm }),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Industry analysis failed');
        }

        const data = await response.json();
        showStatus('success', `Industry analysis complete for ${industry} ${quarter} ${year}`);
        displayIndustryAnalysis(data);
        resultsEl.classList.remove('hidden');

    } catch (error) {
        showStatus('error', error.message);
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Analyze Industry';
    }
}

function displayIndustryAnalysis(data) {
    // Headline
    document.getElementById('headline').textContent = data.headline || 'No headline generated';

    // Themes
    const themesList = document.getElementById('industry-themes');
    themesList.innerHTML = '';
    (data.common_themes || []).forEach(t => {
        const li = document.createElement('li');
        const sentClass = (t.sentiment || 'neutral') + '-bg';
        li.className = sentClass;

        const freq = t.frequency || (t.companies_mentioning || []).length;
        const companies = (t.companies_mentioning || []).join(', ');

        li.innerHTML = `
            <span class="sentiment-dot ${t.sentiment || 'neutral'}"></span>
            ${esc(t.theme)}
            <span class="frequency-bar">${freq}/${data.companies_analyzed ? data.companies_analyzed.length : '?'}</span>
        `;
        if (companies) {
            li.title = companies;
        }
        themesList.appendChild(li);
    });

    // Company comparison table
    buildComparisonTable(data);

    // Divergences
    const divPanel = document.getElementById('divergences-panel');
    const divList = document.getElementById('divergences-list');
    if (data.divergences && data.divergences.length > 0) {
        divPanel.classList.remove('hidden');
        divList.innerHTML = '';
        data.divergences.forEach(d => {
            const li = document.createElement('li');
            li.textContent = d;
            divList.appendChild(li);
        });
    } else {
        divPanel.classList.add('hidden');
    }

    // Narrative
    document.getElementById('narrative').textContent = data.narrative || 'No narrative generated.';
}

async function buildComparisonTable(data) {
    const table = document.getElementById('comparison-table');
    const noData = document.getElementById('no-comparison-data');
    const head = document.getElementById('comparison-head');
    const body = document.getElementById('comparison-body');

    // Fetch individual analyses to build the comparison table
    const companies = data.companies_analyzed || [];
    if (companies.length === 0) {
        table.style.display = 'none';
        noData.style.display = 'block';
        return;
    }

    const quarter = document.getElementById('quarter').value;
    const year = document.getElementById('year').value;

    const analyses = [];
    for (const company of companies) {
        try {
            const resp = await fetch(`${API_BASE}/api/analysis/results/${encodeURIComponent(company)}?quarter=${quarter}&year=${year}`);
            if (resp.ok) {
                analyses.push(await resp.json());
            }
        } catch (e) { /* skip */ }
    }

    if (analyses.length === 0) {
        table.style.display = 'none';
        noData.style.display = 'block';
        return;
    }

    noData.style.display = 'none';
    table.style.display = 'table';

    // Build header
    head.innerHTML = `<tr>
        <th>Company</th>
        <th>Revenue</th>
        <th>Rev YoY%</th>
        <th>EBITDA Margin</th>
        <th>PAT</th>
        <th>PAT YoY%</th>
    </tr>`;

    // Build rows
    body.innerHTML = '';
    analyses.forEach(a => {
        const metrics = a.metrics || [];
        const rev = findMetric(metrics, 'revenue');
        const ebitda = findMetric(metrics, 'ebitda margin');
        const pat = findMetric(metrics, 'pat', 'net profit');

        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${esc(a.company)}</strong></td>
            <td class="value">${rev ? formatVal(rev.value, rev.unit) : '-'}</td>
            <td class="${growthClass(rev?.yoy_growth)}">${formatGrowth(rev?.yoy_growth)}</td>
            <td class="value">${ebitda && ebitda.value != null ? ebitda.value.toFixed(1) + '%' : (ebitda && ebitda.margin != null ? ebitda.margin.toFixed(1) + '%' : '-')}</td>
            <td class="value">${pat ? formatVal(pat.value, pat.unit) : '-'}</td>
            <td class="${growthClass(pat?.yoy_growth)}">${formatGrowth(pat?.yoy_growth)}</td>
        `;
        body.appendChild(row);
    });
}

function findMetric(metrics, ...keywords) {
    for (const kw of keywords) {
        const found = metrics.find(m => m.name.toLowerCase().includes(kw));
        if (found) return found;
    }
    return null;
}

// Helpers
function showStatus(type, message) {
    statusEl.className = `status-bar ${type}`;
    statusEl.textContent = message;
    statusEl.classList.remove('hidden');
}

function formatVal(value, unit) {
    if (value == null) return '-';
    if ((unit || '').includes('Cr')) return `${value.toLocaleString('en-IN', { maximumFractionDigits: 1 })} Cr`;
    return `${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })} ${unit || ''}`;
}

function formatGrowth(growth) {
    if (growth == null) return '-';
    const sign = growth >= 0 ? '+' : '';
    return `${sign}${growth.toFixed(1)}%`;
}

function growthClass(growth) {
    if (growth == null) return 'neutral';
    return growth >= 0 ? 'positive' : 'negative';
}

function esc(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
