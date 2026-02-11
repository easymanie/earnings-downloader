// Multi-Quarter Earnings Analysis Frontend

const API_BASE = '';

const analysisForm = document.getElementById('analysis-form');
const analyzeBtn = document.getElementById('analyze-btn');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');

analysisForm.addEventListener('submit', handleAnalyze);

async function handleAnalyze(e) {
    e.preventDefault();

    const company = document.getElementById('company').value.trim();
    const quarter = document.getElementById('quarter').value;
    const year = document.getElementById('year').value;
    const lookback = parseInt(document.getElementById('lookback').value);
    const llm = document.getElementById('llm').value;

    if (!company) return;

    showStatus('loading', `Analyzing ${company} ${quarter} ${year} + ${lookback - 1} preceding quarters... This may take a few minutes.`);
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Analyzing...';
    resultsEl.classList.add('hidden');

    try {
        const payload = {
            company,
            quarter,
            year,
            lookback_quarters: lookback,
            llm_provider: llm,
        };
        console.log('Sending payload:', JSON.stringify(payload));

        const response = await fetch(`${API_BASE}/api/analysis/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const text = await response.text();
            console.error('API error response:', text);
            throw new Error(text);
        }

        const data = await response.json();
        const numQ = (data.quarters_analyzed || []).length;
        showStatus('success', `Analysis complete: ${company} across ${numQ} quarters`);
        displayMultiQuarterAnalysis(data);
        resultsEl.classList.remove('hidden');

    } catch (error) {
        console.error('Analysis error:', error);
        const msg = error instanceof Error ? error.message : JSON.stringify(error);
        showStatus('error', msg);
    } finally {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Analyze';
    }
}

function displayMultiQuarterAnalysis(data) {
    const quarter = data.target_quarter;
    const year = data.target_year;
    const analyses = data.quarter_analyses || [];

    // --- Section 1: Current Quarter ---
    document.getElementById('current-quarter-heading').textContent =
        `${data.company} — ${quarter} ${year}`;

    // Find the target quarter's analysis (first in list, most recent)
    const current = analyses.length > 0 ? analyses[0] : null;

    if (current) {
        // Metrics
        const metricsBody = document.getElementById('metrics-body');
        metricsBody.innerHTML = '';
        (current.metrics || []).forEach(m => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${esc(m.name)}</td>
                <td class="value">${formatValue(m.value, m.unit)}</td>
                <td class="${growthClass(m.qoq_growth)}">${formatGrowth(m.qoq_growth)}</td>
                <td class="${growthClass(m.yoy_growth)}">${formatGrowth(m.yoy_growth)}</td>
                <td>${m.margin != null ? m.margin.toFixed(1) + '%' : '-'}</td>
            `;
            metricsBody.appendChild(row);
        });

        // Themes
        const themesList = document.getElementById('themes-list');
        themesList.innerHTML = '';
        (current.themes || []).forEach(theme => {
            const li = document.createElement('li');
            li.className = 'neutral-bg';
            li.innerHTML = `<span class="sentiment-dot neutral"></span> ${esc(theme)}`;
            themesList.appendChild(li);
        });

        // Highlights
        const highlightsList = document.getElementById('highlights-list');
        highlightsList.innerHTML = '';
        (current.key_highlights || []).forEach(h => {
            const li = document.createElement('li');
            li.textContent = h;
            highlightsList.appendChild(li);
        });

        // Commentary
        const commentaryList = document.getElementById('commentary-list');
        commentaryList.innerHTML = '';
        (current.commentary || []).forEach(c => {
            const div = document.createElement('div');
            div.className = 'commentary-item';
            let html = `
                <div class="topic">${esc(c.topic)} <span class="sentiment-dot ${c.sentiment}" style="display:inline-block;vertical-align:middle;"></span></div>
                <div class="summary">${esc(c.summary)}</div>
            `;
            if (c.verbatim_quote) {
                html += `<div class="quote">"${esc(c.verbatim_quote)}"</div>`;
            }
            div.innerHTML = html;
            commentaryList.appendChild(div);
        });

        // Guidance
        const guidancePanel = document.getElementById('guidance-panel');
        if (current.guidance) {
            guidancePanel.classList.remove('hidden');
            document.getElementById('guidance-text').textContent = current.guidance;
        } else {
            guidancePanel.classList.add('hidden');
        }
    }

    // --- Section 2: Trend Context ---
    const numQ = (data.quarters_analyzed || []).length;
    document.getElementById('trend-heading').textContent =
        `Trend Context (${numQ} Quarters)`;

    // Consistency assessment
    document.getElementById('consistency-box').textContent =
        data.consistency_assessment || 'No trend data available.';

    // Current quarter summary
    document.getElementById('quarter-summary').textContent =
        data.current_quarter_summary || '';

    // Metric Trends
    const trendsDiv = document.getElementById('metric-trends-list');
    trendsDiv.innerHTML = '';
    (data.metric_trends || []).forEach(t => {
        const div = document.createElement('div');
        div.className = `change-item ${t.notable ? 'material' : 'notable'}`;
        const icon = directionIcon(t.direction);
        div.innerHTML = `
            <span><strong>${esc(t.metric)}</strong>: ${esc(t.trend)}</span>
            <span class="change-badge ${directionClass(t.direction)}">${icon} ${esc(t.direction)}</span>
        `;
        trendsDiv.appendChild(div);
    });

    // Metrics Over Time table
    buildMetricsOverTime(analyses);

    // Theme Evolution
    buildThemeSection('theme-persistent', 'Persistent', data.persistent_themes || [], 'positive');
    buildThemeSection('theme-emerging', 'Emerging', data.emerging_themes || [], 'neutral');
    buildThemeSection('theme-fading', 'Fading', data.fading_themes || [], 'negative');

    // Narrative Shifts
    const shiftsPanel = document.getElementById('narrative-shifts-panel');
    const shiftsList = document.getElementById('narrative-shifts-list');
    if (data.narrative_shifts && data.narrative_shifts.length > 0) {
        shiftsPanel.classList.remove('hidden');
        shiftsList.innerHTML = '';
        data.narrative_shifts.forEach(s => {
            const li = document.createElement('li');
            li.textContent = s;
            shiftsList.appendChild(li);
        });
    } else {
        shiftsPanel.classList.add('hidden');
    }
}

function buildMetricsOverTime(analyses) {
    // analyses is most-recent-first; reverse for chronological display
    const chrono = [...analyses].reverse();
    const head = document.getElementById('mot-head');
    const body = document.getElementById('mot-body');

    if (chrono.length === 0) {
        head.innerHTML = '';
        body.innerHTML = '<tr><td>No data</td></tr>';
        return;
    }

    // Header: Metric | Q4 FY25 | Q1 FY26 | Q2 FY26 | Q3 FY26
    head.innerHTML = '<tr><th>Metric</th>' +
        chrono.map(a => `<th>${a.quarter} ${a.year}</th>`).join('') +
        '</tr>';

    // Collect all unique metric names from the most recent quarter
    const latestMetrics = chrono[chrono.length - 1].metrics || [];
    const metricNames = latestMetrics.map(m => m.name);

    body.innerHTML = '';
    metricNames.forEach(name => {
        const row = document.createElement('tr');
        let html = `<td><strong>${esc(name)}</strong></td>`;

        chrono.forEach(a => {
            const metric = (a.metrics || []).find(m => m.name.toLowerCase() === name.toLowerCase());
            if (metric && metric.value != null) {
                html += `<td class="value">${formatValue(metric.value, metric.unit)}</td>`;
            } else {
                html += '<td class="neutral">-</td>';
            }
        });

        row.innerHTML = html;
        body.appendChild(row);
    });
}

function buildThemeSection(elementId, label, themes, sentiment) {
    const el = document.getElementById(elementId);
    if (!themes || themes.length === 0) {
        el.innerHTML = '';
        return;
    }

    const colorMap = {
        positive: { bg: '#ecfdf5', dot: '#059669', text: 'Recurring across quarters' },
        neutral: { bg: '#eff6ff', dot: '#2563eb', text: 'New in recent quarters' },
        negative: { bg: '#fef2f2', dot: '#dc2626', text: 'No longer mentioned' },
    };
    const c = colorMap[sentiment] || colorMap.neutral;

    el.innerHTML = `
        <div style="margin-bottom:12px;">
            <strong style="font-size:0.85rem;color:#374151;">${label}</strong>
            <span style="font-size:0.75rem;color:#6b7280;margin-left:6px;">${c.text}</span>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;">
            ${themes.map(t => `<span class="chip" style="background:${c.bg};color:${c.dot};border:1px solid ${c.dot}30;">${esc(t)}</span>`).join('')}
        </div>
    `;
}

// Helpers
function showStatus(type, message) {
    statusEl.className = `status-bar ${type}`;
    statusEl.textContent = message;
    statusEl.classList.remove('hidden');
}

function formatValue(value, unit) {
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

function directionIcon(dir) {
    const icons = {
        improving: '\u2191', declining: '\u2193', stable: '\u2194',
        stable_growth: '\u2197', stable_decline: '\u2198',
        volatile: '\u2195', recovering: '\u21A9',
    };
    return icons[dir] || '';
}

function directionClass(dir) {
    if (['improving', 'stable_growth', 'recovering'].includes(dir)) return 'improved';
    if (['declining', 'stable_decline'].includes(dir)) return 'declined';
    return '';
}

function esc(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}
