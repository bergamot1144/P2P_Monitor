let timer = null; const REFRESH_MS = 30000;
let xeTimer = null; const XE_REFRESH_MS = 30000;
let gfTimer = null; const GF_REFRESH_MS = 30000;

let lastBinanceAvg = null;
let lastBybitAvg = null;
let lastGfPrice = null;
window.__lastXePrice = null;

let selectedBinance = new Set();
let selectedBybit = new Set();
const tempSelected = { dd_binance: new Set(), dd_bybit: new Set() };
const searchState = { dd_binance: "", dd_bybit: "" };
let binanceItems = []; let bybitItems = [];

function fmtSmart(n) {
    const v = Number(n);
    if (!isFinite(v)) return '—';
    const opts = v >= 1_000_000 ? { minimumFractionDigits: 0, maximumFractionDigits: 2 }
        : { minimumFractionDigits: 2, maximumFractionDigits: 6 };
    return v.toLocaleString('ru-RU', opts);
}
function fmt(n) { return Number(n).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 6 }); }
function fmtShort(n) { return Number(n).toLocaleString('ru-RU', { maximumFractionDigits: 6 }); }
function showLoader(id) { const el = document.getElementById(id); if (el) el.style.display = 'flex'; }
function hideLoader(id) { const el = document.getElementById(id); if (el) el.style.display = 'none'; }

function updateSpreads() {
    if (lastGfPrice != null) {
        const s1 = (lastBinanceAvg == null) ? null : ((lastBinanceAvg - lastGfPrice) / lastGfPrice * 100);
        const s2 = (lastBybitAvg == null) ? null : ((lastBybitAvg - lastGfPrice) / lastGfPrice * 100);
        document.getElementById('gf_spread_bin').innerHTML = s1 == null ? '—' : ((s1 > 0 ? '+' : '') + s1.toFixed(2) + '%');
        document.getElementById('gf_spread_byb').innerHTML = s2 == null ? '—' : ((s2 > 0 ? '+' : '') + s2.toFixed(2) + '%');
    }
    if (window.__lastXePrice != null) {
        const base = window.__lastXePrice;
        const s1 = (lastBinanceAvg == null) ? null : ((lastBinanceAvg - base) / base * 100);
        const s2 = (lastBybitAvg == null) ? null : ((lastBybitAvg - base) / base * 100);
        document.getElementById('xe_spread_bin').innerHTML = s1 == null ? '—' : ((s1 > 0 ? '+' : '') + s1.toFixed(2) + '%');
        document.getElementById('xe_spread_byb').innerHTML = s2 == null ? '—' : ((s2 > 0 ? '+' : '') + s2.toFixed(2) + '%');
    }
}

function toggleFilters(id, btn) {
    const el = document.getElementById(id);
    const hidden = window.getComputedStyle(el).display === 'none';
    el.style.display = hidden ? '' : 'none';
    if (btn) btn.textContent = hidden ? 'Скрыть фильтры' : 'Фильтры';
    if (hidden) {
        if (id === 'binance_filters') loadBinancePaytypes();
        if (id === 'bybit_filters') loadBybitPayments();
    } else {
        closeAllDropdowns();
    }
}

function mdropToggle(ddId) {
    const dd = document.getElementById(ddId);
    if (dd.classList.contains('open')) {
        closeAndClear(ddId);
        return;
    }
    closeAllDropdowns();
    dd.classList.add('open');
    tempSelected[ddId] = new Set([...(ddId === 'dd_binance' ? selectedBinance : selectedBybit)]);
    renderDropdownOptions(ddId);
    const input = document.getElementById(ddId + '_search');
    if (input) { input.value = searchState[ddId] || ""; input.focus(); }
}
function closeAndClear(ddId) {
    const dd = document.getElementById(ddId);
    if (!dd) return;
    dd.classList.remove('open');
    searchState[ddId] = "";
    const input = document.getElementById(ddId + '_search');
    if (input) input.value = "";
}
function closeAllDropdowns() {
    document.querySelectorAll('.mdrop.open').forEach(dd => {
        const id = dd.id;
        dd.classList.remove('open');
        searchState[id] = "";
        const input = document.getElementById(id + '_search');
        if (input) input.value = "";
    });
}
document.addEventListener('pointerdown', (e) => {
    const openDd = document.querySelector('.mdrop.open');
    if (!openDd) return;
    if (openDd.contains(e.target)) return;
    closeAllDropdowns();
}, true);
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAllDropdowns(); });

function onSearchInput(ddId) {
    const input = document.getElementById(ddId + '_search');
    const val = (input?.value || '').toLowerCase().trim();
    searchState[ddId] = val;
    renderDropdownOptions(ddId);
}
function filteredItems(ddId) {
    const list = (ddId === 'dd_binance') ? binanceItems : bybitItems;
    const q = (searchState[ddId] || '').toLowerCase();
    if (!q) return list;
    return list.filter(it => (String(it.name || '') + ' ' + String(it.id || '')).toLowerCase().includes(q));
}
function renderDropdownOptions(ddId) {
    const isBin = ddId === 'dd_binance';
    const items = filteredItems(ddId);
    const temp = tempSelected[ddId];
    const gridId = isBin ? 'dd_binance_grid' : 'dd_bybit_grid';
    const grid = document.getElementById(gridId);
    grid.innerHTML = '';
    items.forEach(it => {
        const id = String(it.id);
        const name = it.name || id;
        const btn = document.createElement('div');
        btn.className = 'mdrop-pill' + (temp.has(id) ? ' active' : '');
        btn.textContent = name;
        btn.title = name;
        btn.dataset.id = id;
        btn.addEventListener('click', () => {
            if (temp.has(id)) temp.delete(id); else temp.add(id);
            btn.classList.toggle('active');
            const cntSpan = document.getElementById(isBin ? 'dd_binance_count' : 'dd_bybit_count');
            cntSpan.textContent = String(temp.size);
        });
        grid.appendChild(btn);
    });
    const cntSpan = document.getElementById(isBin ? 'dd_binance_count' : 'dd_bybit_count');
    cntSpan.textContent = String(temp.size);
    wireDropdown(ddId);
}
function updateCounters() {
    document.getElementById('dd_binance_count').textContent = String(selectedBinance.size);
    document.getElementById('dd_bybit_count').textContent = String(selectedBybit.size);
}
function wireDropdown(ddId) {
    const root = document.getElementById(ddId);
    if (!root) return;
    const menu = root.querySelector('.mdrop-menu');
    if (!menu || menu.__wired) return;
    menu.addEventListener('click', (e) => {
        e.stopPropagation();
        if (e.target.closest('.js-confirm')) {
            if (ddId === 'dd_binance') selectedBinance = new Set([...tempSelected[ddId]]);
            if (ddId === 'dd_bybit') selectedBybit = new Set([...tempSelected[ddId]]);
            updateCounters();
            refreshNow();
            closeAllDropdowns();
            return;
        }
        if (e.target.closest('.js-reset')) {
            tempSelected[ddId] = new Set();
            renderDropdownOptions(ddId);
            const cntSpan = document.getElementById(ddId === 'dd_binance' ? 'dd_binance_count' : 'dd_bybit_count');
            if (cntSpan) cntSpan.textContent = '0';
            return;
        }
    });
    menu.__wired = true;
}

async function loadBinancePaytypes() {
    const asset = document.getElementById('asset').value;
    const fiat = document.getElementById('fiat').value;
    const side = document.getElementById('side').value;
    const amount = document.getElementById('amount').value;
    const merch = document.getElementById('merchant_binance')?.value ?? 'true';
    const url = '/api/binance/paytypes?' + new URLSearchParams({ asset, fiat, side, amount, merchant_binance: merch });
    try {
        const r = await fetch(url);
        const js = await r.json();
        binanceItems = js.items || [];
        [...selectedBinance].forEach(id => { if (!binanceItems.find(it => String(it.id) === id)) selectedBinance.delete(id); });
        updateCounters();
        return binanceItems;
    } catch (e) {
        binanceItems = []; selectedBinance.clear(); updateCounters();
        return [];
    }
}
async function loadBybitPayments() {
    const fiat = document.getElementById('fiat').value;
    try {
        const r = await fetch('/api/bybit/payments?fiat=' + encodeURIComponent(fiat));
        const js = await r.json();
        bybitItems = js.items || [];
        [...selectedBybit].forEach(id => { if (!bybitItems.find(it => String(it.id) === id)) selectedBybit.delete(id); });
        updateCounters();
        return bybitItems;
    } catch (e) {
        bybitItems = []; selectedBybit.clear(); updateCounters();
        return [];
    }
}

function paramsFromUI() {
    return {
        asset: document.getElementById('asset').value,
        fiat: document.getElementById('fiat').value,
        side: document.getElementById('side').value,
        amount: document.getElementById('amount').value,
        merchant_binance: document.getElementById('merchant_binance')?.value ?? 'true',
        paytypes_binance: [...selectedBinance].join(','),
        verified_bybit: document.getElementById('verified_bybit')?.value ?? 'false',
        payments_bybit: [...selectedBybit].join(',')
    };
}

async function loadBinance() {
    const p = paramsFromUI();
    const url = '/api/binance_rate?' + new URLSearchParams({ asset: p.asset, fiat: p.fiat, side: p.side, amount: p.amount, paytypes: p.paytypes_binance, merchant: p.merchant_binance }).toString();
    showLoader('binance_loader');
    try {
        const res = await fetch(url);
        const data = await res.json();
        const bErr = document.getElementById('binance_error');
        const bOk = document.getElementById('binance_status');
        if (!data.ok) {
            bErr.style.display = ''; bErr.textContent = 'Ошибка: ' + (data.error || 'unknown');
            bOk.style.display = 'none';
            document.getElementById('binance_avg').textContent = '—';
            document.getElementById('binance_prices').textContent = '—';
            document.getElementById('binance_tbody').innerHTML = '';
            lastBinanceAvg = null;
        } else {
            bErr.style.display = 'none'; bOk.style.display = '';
            document.getElementById('binance_avg').textContent = (data.avg != null ? fmt(data.avg) : '—') + ' ' + p.fiat;
            document.getElementById('binance_prices').textContent = data.prices && data.prices.length ? ('#3–5: ' + data.prices.slice(2, 5).map(fmt).join(' • ')) : '—';
            const tb = document.getElementById('binance_tbody'); tb.innerHTML = '';
            (data.items || []).forEach((it, i) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${i + 1}</td><td>${it.name || '-'}</td><td>${fmt(it.price)}</td><td>${it.volume ?? '-'}</td><td>${it.min ?? '-'}</td><td>${it.max ?? '-'}</td>`;
                tb.appendChild(tr);
            });
            lastBinanceAvg = data.avg ?? null;
        }
    } catch (e) {
        const bErr = document.getElementById('binance_error');
        bErr.style.display = ''; bErr.textContent = 'Ошибка сети';
        document.getElementById('binance_status').style.display = 'none';
        document.getElementById('binance_avg').textContent = '—';
        document.getElementById('binance_prices').textContent = '—';
        document.getElementById('binance_tbody').innerHTML = '';
        lastBinanceAvg = null;
    } finally {
        hideLoader('binance_loader');
        updateSpreads();
    }
}

async function loadBybit() {
    const p = paramsFromUI();
    const url = '/api/bybit_rate?' + new URLSearchParams({ asset: p.asset, fiat: p.fiat, side: p.side, amount: p.amount, payments: p.payments_bybit, verified: p.verified_bybit }).toString();
    showLoader('bybit_loader');
    try {
        const res = await fetch(url);
        const data = await res.json();
        const yErr = document.getElementById('bybit_error');
        const yOk = document.getElementById('bybit_status');
        if (!data.ok) {
            yErr.style.display = ''; yErr.textContent = 'Ошибка: ' + (data.error || 'unknown');
            yOk.style.display = 'none';
            document.getElementById('bybit_avg').textContent = '—';
            document.getElementById('bybit_prices').textContent = '—';
            document.getElementById('bybit_tbody').innerHTML = '';
            lastBybitAvg = null;
        } else {
            yErr.style.display = 'none'; yOk.style.display = '';
            document.getElementById('bybit_avg').textContent = (data.avg != null ? fmt(data.avg) : '—') + ' ' + p.fiat;
            document.getElementById('bybit_prices').textContent = data.prices && data.prices.length ? ('#3–5: ' + data.prices.slice(2, 5).map(fmt).join(' • ')) : '—';
            const tb = document.getElementById('bybit_tbody'); tb.innerHTML = '';
            (data.items || []).forEach((it, i) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${i + 1}</td><td>${it.name || '-'}</td><td>${fmt(it.price)}</td><td>${it.volume ?? '-'}</td><td>${it.min ?? '-'}</td><td>${it.max ?? '-'}</td>`;
                tb.appendChild(tr);
            });
            lastBybitAvg = data.avg ?? null;
        }
    } catch (e) {
        const yErr = document.getElementById('bybit_error');
        yErr.style.display = ''; yErr.textContent = 'Ошибка сети';
        document.getElementById('bybit_status').style.display = 'none';
        document.getElementById('bybit_avg').textContent = '—';
        document.getElementById('bybit_prices').textContent = '—';
        document.getElementById('bybit_tbody').innerHTML = '';
        lastBybitAvg = null;
    } finally {
        hideLoader('bybit_loader');
        updateSpreads();
    }
}

async function fillXeCodes() {
    try {
        const r = await fetch('/api/xe/codes');
        const js = await r.json();
        const list = (js.codes || []).sort();
        const dl = document.getElementById('xe_codes');
        const dl2 = document.getElementById('gf_codes');
        dl.innerHTML = ''; dl2.innerHTML = '';
        list.forEach(code => {
            const opt1 = document.createElement('option'); opt1.value = code; dl.appendChild(opt1);
            const opt2 = document.createElement('option'); opt2.value = code; dl2.appendChild(opt2);
        });
        if (!document.getElementById('xe_from').value) document.getElementById('xe_from').value = 'USD';
        if (!document.getElementById('xe_to').value) document.getElementById('xe_to').value = document.getElementById('fiat').value || 'UAH';
        if (!document.getElementById('gf_from').value) document.getElementById('gf_from').value = 'USD';
        if (!document.getElementById('gf_to').value) document.getElementById('gf_to').value = document.getElementById('fiat').value || 'UAH';
    } catch (e) { }
}
function currentXePair() {
    const f = (document.getElementById('xe_from').value || '').toUpperCase().trim();
    const t = (document.getElementById('xe_to').value || '').toUpperCase().trim();
    if (!f || !t) return null; return { from: f, to: t };
}
function applyXE() {
    refreshXENow();
    const pr = currentXePair();
    if (pr) history.replaceState(null, '', '?' + new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(location.search)), xe_from: pr.from, xe_to: pr.to }).toString());
}
async function loadXE() {
    const pr = currentXePair();
    const err = document.getElementById('xe_error');
    if (!pr) {
        err.style.display = ''; err.textContent = 'Укажите пары XE (From/To).';
        return;
    }
    const url = '/api/xe?' + new URLSearchParams({ from: pr.from, to: pr.to }).toString();
    showLoader('xe_loader');
    try {
        const r = await fetch(url);
        const js = await r.json();
        document.getElementById('xe_pair').textContent = `${pr.from}-${pr.to}`;
        if (!js.ok) {
            err.style.display = ''; err.textContent = 'Ошибка XE: ' + (js.error || 'unknown');
            document.getElementById('xe_price').textContent = '—';
            document.getElementById('xe_ts').textContent = '—';
            document.getElementById('xe_src').textContent = '—';
            document.getElementById('xe_link').href = '#';
            document.getElementById('xe_spread_bin').textContent = '—';
            document.getElementById('xe_spread_byb').textContent = '—';
            window.__lastXePrice = null;
        } else {
            err.style.display = 'none';
            const d = js.data;
            document.getElementById('xe_price').textContent = fmtSmart(d.price) + ' ' + pr.to;
            document.getElementById('xe_ts').textContent = 'TS: ' + new Date(d.ts * 1000).toLocaleTimeString('ru-RU');
            document.getElementById('xe_src').textContent = d.source || 'xe';
            document.getElementById('xe_link').href = d.url || '#';
            window.__lastXePrice = d.price;
        }
    } catch (e) {
        err.style.display = ''; err.textContent = 'Ошибка сети/парсинга XE';
        document.getElementById('xe_spread_bin').textContent = '—';
        document.getElementById('xe_spread_byb').textContent = '—';
        window.__lastXePrice = null;
    } finally {
        hideLoader('xe_loader');
        updateSpreads();

    }
}

function currentGfPair() {
    const f = (document.getElementById('gf_from').value || '').toUpperCase().trim();
    const t = (document.getElementById('gf_to').value || '').toUpperCase().trim();
    if (!f || !t) return null; return { from: f, to: t };
}
function applyGF() {
    refreshGFNow();
    const pr = currentGfPair();
    if (pr) history.replaceState(null, '', '?' + new URLSearchParams({ ...Object.fromEntries(new URLSearchParams(location.search)), gf_from: pr.from, gf_to: pr.to }).toString());
}
async function loadGF() {
    const pr = currentGfPair();
    const gErr = document.getElementById('gf_error');
    if (!pr) {
        gErr.style.display = ''; gErr.textContent = 'Укажите пары GF (From/To).';
        return;
    }
    document.getElementById('gf_pair').textContent = `${pr.from}-${pr.to}`;
    const url = '/api/gf_rate?' + new URLSearchParams({ asset: pr.from, fiat: pr.to }).toString();
    showLoader('gf_loader');
    try {
        const r = await fetch(url);
        const js = await r.json();
        if (!js.ok) {
            gErr.style.display = ''; gErr.textContent = 'GF ошибка: ' + (js.error || 'unknown');
            document.getElementById('gf_price').textContent = '—';
            document.getElementById('gf_ts').textContent = '—';
            document.getElementById('gf_link').href = '#';
            document.getElementById('gf_spread_bin').textContent = '—';
            document.getElementById('gf_spread_byb').textContent = '—';
            lastGfPrice = null;
        } else {
            gErr.style.display = 'none';
            document.getElementById('gf_price').textContent = fmtShort(js.price) + ' ' + pr.to;
            document.getElementById('gf_ts').textContent = 'TS: ' + new Date(js.ts * 1000).toLocaleTimeString('ru-RU');
            document.getElementById('gf_link').href = js.url || '#';
            lastGfPrice = js.price;
        }
    } catch (e) {
        gErr.style.display = ''; gErr.textContent = 'Ошибка сети/парсинга GF';
        document.getElementById('gf_spread_bin').textContent = '—';
        document.getElementById('gf_spread_byb').textContent = '—';
        lastGfPrice = null;
    } finally {
        hideLoader('gf_loader');
        updateSpreads();
    }
}
function refreshGFNow() { loadGF(); if (gfTimer) clearInterval(gfTimer); gfTimer = setInterval(loadGF, GF_REFRESH_MS); }

function refreshNow() {
    loadBinance();
    loadBybit();
    document.getElementById('ts').textContent = '• обновлено: ' + new Date().toLocaleTimeString('ru-RU');
    if (timer) clearInterval(timer);
    timer = setInterval(() => { loadBinance(); loadBybit(); document.getElementById('ts').textContent = '• обновлено: ' + new Date().toLocaleTimeString('ru-RU'); }, REFRESH_MS);
}
function refreshXENow() { loadXE(); if (xeTimer) clearInterval(xeTimer); xeTimer = setInterval(loadXE, XE_REFRESH_MS); }
function apply(ev) { ev.preventDefault(); refreshNow(); refreshXENow(); refreshGFNow(); }

window.addEventListener('DOMContentLoaded', async () => {
    await fillXeCodes();

    const q = new URLSearchParams(location.search);
    const xf = q.get('xe_from'); const xt = q.get('xe_to');
    const gfF = q.get('gf_from'); const gfT = q.get('gf_to');
    if (xf) document.getElementById('xe_from').value = xf;
    if (xt) document.getElementById('xe_to').value = xt;
    if (gfF) document.getElementById('gf_from').value = gfF;
    if (gfT) document.getElementById('gf_to').value = gfT;

    await loadBinancePaytypes();
    await loadBybitPayments();
    updateCounters();

    document.getElementById('asset').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('fiat').addEventListener('change', () => { loadBinancePaytypes(); loadBybitPayments(); refreshNow(); });
    document.getElementById('side').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('amount').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('merchant_binance')?.addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('verified_bybit')?.addEventListener('change', () => { refreshNow(); });

    refreshNow();
    refreshXENow();
    refreshGFNow();
});