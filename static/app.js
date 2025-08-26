/* ====== app.js (P2P Dashboard) ====== */

/* интервалы */
let timer = null; const REFRESH_MS = 30000;
let xeTimer = null; const XE_REFRESH_MS = 30000;
let gfTimer = null; const GF_REFRESH_MS = 30000;

/* состояние */
let lastBinanceAvg = null;
let lastBybitAvg = null;
let lastGfPrice = null;
window.__lastXePrice = null;

/* мультидропы */
let selectedBinance = new Set();
let selectedBybit = new Set();
const tempSelected = { dd_binance: new Set(), dd_bybit: new Set() };
const searchState = { dd_binance: "", dd_bybit: "" };
let binanceItems = []; let bybitItems = [];

/* ===== DOM-хелперы ===== */
const $ = (id) => document.getElementById(id);

/* утилиты */
function fmtSmart(n) { const v = Number(n); if (!isFinite(v)) return '—'; const o = v >= 1_000_000 ? { minimumFractionDigits: 0, maximumFractionDigits: 2 } : { minimumFractionDigits: 2, maximumFractionDigits: 6 }; return v.toLocaleString('ru-RU', o); }
function fmt(n) { return Number(n).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 6 }); }
function fmtShort(n) { return Number(n).toLocaleString('ru-RU', { maximumFractionDigits: 6 }); }
function showLoader(id) { const el = $(id); if (el) el.style.display = 'flex'; }
function hideLoader(id) { const el = $(id); if (el) el.style.display = 'none'; }
function setAnimatedText(el, text, prevNumeric, nextNumeric) {
    if (!el) return;
    el.textContent = text;
    if (typeof prevNumeric === 'number' && typeof nextNumeric === 'number' && isFinite(prevNumeric) && isFinite(nextNumeric) && prevNumeric !== nextNumeric) {
        el.classList.remove('updated'); void el.offsetWidth; el.classList.add('updated');
    }
}

/* ===== раскрытие фильтров ===== */
function toggleFilters(id, btn) {
    const el = $(id);
    if (!el) return;
    const willShow = el.getAttribute('aria-hidden') !== 'false';
    el.setAttribute('aria-hidden', willShow ? 'false' : 'true');
    if (btn) btn.textContent = willShow ? 'Скрыть фильтры' : 'Фильтры';
    if (willShow) {
        if (id === 'binance_filters') loadBinancePaytypes();
        if (id === 'bybit_filters') loadBybitPayments();
    } else {
        closeAllDropdowns();
    }
}

/* ===== позиционирование меню ===== */
function positionDropdownMenu(ddId) {
    const root = $(ddId); if (!root) return;
    const menu = root.querySelector('.mdrop-menu'); if (!menu) return;
    menu.classList.remove('drop-up');
    const rect = menu.getBoundingClientRect();
    const vh = document.documentElement.clientHeight;
    const spaceBelow = vh - rect.top;
    const minNeeded = 240;
    if (spaceBelow < minNeeded) { menu.classList.add('drop-up'); }
}
function attachDropdownRepositioning(ddId) {
    const handler = () => positionDropdownMenu(ddId);
    window.addEventListener('resize', handler);
    window.addEventListener('scroll', handler, true);
    const root = $(ddId);
    const obs = new MutationObserver(() => {
        if (!root.classList.contains('open')) {
            window.removeEventListener('resize', handler);
            window.removeEventListener('scroll', handler, true);
            obs.disconnect();
        }
    });
    obs.observe(root, { attributes: true, attributeFilter: ['class'] });
}

/* ===== мультидроп ===== */
function mdropToggle(ddId) {
    const dd = $(ddId);
    if (dd.classList.contains('open')) {
        closeAndClear(ddId);
        return;
    }

    closeAllDropdowns();
    dd.classList.add('open');

    // поднять карточку над соседями
    const card = dd.closest('.card');
    if (card) card.classList.add('raised');

    tempSelected[ddId] = new Set([...(ddId === 'dd_binance' ? selectedBinance : selectedBybit)]);
    renderDropdownOptions(ddId);

    const input = $(ddId + '_search');
    if (input) { input.value = searchState[ddId] || ""; input.focus(); }

    positionDropdownMenu(ddId);
    attachDropdownRepositioning(ddId);
}

function closeAndClear(ddId) {
    const dd = $(ddId);
    if (!dd) return;
    dd.classList.remove('open');
    searchState[ddId] = "";
    const input = $(ddId + '_search');
    if (input) input.value = "";

    // опустить карточку обратно
    const card = dd.closest('.card');
    if (card) card.classList.remove('raised');
}$
function closeAllDropdowns() {
    document.querySelectorAll('.mdrop.open').forEach(dd => {
        const id = dd.id;
        dd.classList.remove('open');
        searchState[id] = "";
        const input = $(id + '_search');
        if (input) input.value = "";
        const card = dd.closest('.card');
        if (card) card.classList.remove('raised');
    });
}

document.addEventListener('pointerdown', (e) => { const openDd = document.querySelector('.mdrop.open'); if (!openDd) return; if (openDd.contains(e.target)) return; closeAllDropdowns(); }, true);
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAllDropdowns(); });

function onSearchInput(ddId) { const input = $(ddId + '_search'); const val = (input?.value || '').toLowerCase().trim(); searchState[ddId] = val; renderDropdownOptions(ddId); positionDropdownMenu(ddId); }
function filteredItems(ddId) { const list = (ddId === 'dd_binance') ? binanceItems : bybitItems; const q = (searchState[ddId] || '').toLowerCase(); if (!q) return list; return list.filter(it => (String(it.name || '') + ' ' + String(it.id || '')).toLowerCase().includes(q)); }
function renderDropdownOptions(ddId) {
    const isBin = ddId === 'dd_binance'; const items = filteredItems(ddId); const temp = tempSelected[ddId];
    const grid = $(isBin ? 'dd_binance_grid' : 'dd_bybit_grid'); grid.innerHTML = '';
    items.forEach(it => {
        const id = String(it.id); const name = it.name || id; const btn = document.createElement('div');
        btn.className = 'mdrop-pill' + (temp.has(id) ? ' active' : ''); btn.textContent = name; btn.title = name; btn.dataset.id = id;
        btn.addEventListener('click', () => {
            if (temp.has(id)) temp.delete(id); else temp.add(id); btn.classList.toggle('active');
            const cnt = $(isBin ? 'dd_binance_count' : 'dd_bybit_count'); cnt.textContent = String(temp.size);
        });
        grid.appendChild(btn);
    });
    const cnt = $(isBin ? 'dd_binance_count' : 'dd_bybit_count'); cnt.textContent = String(temp.size);
    wireDropdown(ddId);
}
function updateCounters() { $('dd_binance_count').textContent = String(selectedBinance.size); $('dd_bybit_count').textContent = String(selectedBybit.size); }
function wireDropdown(ddId) {
    const root = $(ddId); if (!root) return;
    const menu = root.querySelector('.mdrop-menu'); if (!menu || menu.__wired) return;
    menu.addEventListener('click', (e) => {
        e.stopPropagation();
        if (e.target.closest('.js-confirm')) {
            if (ddId === 'dd_binance') selectedBinance = new Set([...tempSelected[ddId]]);
            if (ddId === 'dd_bybit') selectedBybit = new Set([...tempSelected[ddId]]);
            updateCounters(); refreshNow(); closeAllDropdowns(); return;
        }
        if (e.target.closest('.js-reset')) {
            tempSelected[ddId] = new Set(); renderDropdownOptions(ddId);
            const cnt = $(ddId === 'dd_binance' ? 'dd_binance_count' : 'dd_bybit_count'); if (cnt) cnt.textContent = '0'; return;
        }
    });
    menu.__wired = true;
}

/* ===== API-справочники ===== */
async function loadBinancePaytypes() {
    const asset = $('asset').value;
    const fiat = $('fiat').value;
    const side = $('side').value;
    const amount = $('amount').value;
    const merch = $('merchant_binance')?.checked ? 'true' : 'false';
    const url = '/api/binance/paytypes?' + new URLSearchParams({ asset, fiat, side, amount, merchant_binance: merch });
    try {
        const r = await fetch(url); const js = await r.json();
        binanceItems = js.items || [];
        [...selectedBinance].forEach(id => { if (!binanceItems.find(it => String(it.id) === id)) selectedBinance.delete(id); });
        updateCounters(); return binanceItems;
    } catch {
        binanceItems = []; selectedBinance.clear(); updateCounters(); return [];
    }
}
async function loadBybitPayments() {
    const fiat = $('fiat').value;
    try {
        const r = await fetch('/api/bybit/payments?fiat=' + encodeURIComponent(fiat)); const js = await r.json();
        bybitItems = js.items || [];
        [...selectedBybit].forEach(id => { if (!bybitItems.find(it => String(it.id) === id)) selectedBybit.delete(id); });
        updateCounters(); return bybitItems;
    } catch { bybitItems = []; selectedBybit.clear(); updateCounters(); return []; }
}

/* ===== параметры ===== */
function paramsFromUI() {
    return {
        asset: $('asset').value,
        fiat: $('fiat').value,
        side: $('side').value,
        amount: $('amount').value,
        merchant_binance: $('merchant_binance')?.checked ? 'true' : 'false',
        paytypes_binance: [...selectedBinance].join(','),
        verified_bybit: $('verified_bybit')?.checked ? 'true' : 'false',
        payments_bybit: [...selectedBybit].join(',')
    };
}

/* ===== загрузка котировок ===== */
async function loadBinance() {
    const p = paramsFromUI();
    const url = '/api/binance_rate?' + new URLSearchParams({ asset: p.asset, fiat: p.fiat, side: p.side, amount: p.amount, paytypes: p.paytypes_binance, merchant: p.merchant_binance });
    showLoader('binance_loader');
    try {
        const res = await fetch(url); const data = await res.json();
        const e = $('binance_error'); const ok = $('binance_status');
        if (!data.ok) {
            e.style.display = ''; e.textContent = 'Ошибка: ' + (data.error || 'unknown'); ok.style.display = 'none';
            $('binance_avg').textContent = '—'; $('binance_prices').textContent = '—'; $('binance_tbody').innerHTML = ''; lastBinanceAvg = null;
        } else {
            e.style.display = 'none'; ok.style.display = '';
            const next = data.avg ?? null;
            setAnimatedText($('binance_avg'), (next != null ? fmt(next) : '—') + ' ' + p.fiat, lastBinanceAvg, next);
            $('binance_prices').textContent = data.prices && data.prices.length ? ('#3–5: ' + data.prices.slice(2, 5).map(fmt).join(' • ')) : '—';
            const tb = $('binance_tbody'); tb.innerHTML = '';
            (data.items || []).forEach((it, i) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${i + 1}</td><td>${it.name || '-'}</td><td>${fmt(it.price)}</td><td>${it.volume ?? '-'}</td><td>${it.min ?? '-'}</td><td>${it.max ?? '-'}</td>`;
                tb.appendChild(tr);
            });
            lastBinanceAvg = next;
        }
    } catch {
        const e = $('binance_error'); e.style.display = ''; e.textContent = 'Ошибка сети';
        $('binance_status').style.display = 'none'; $('binance_avg').textContent = '—'; $('binance_prices').textContent = '—'; $('binance_tbody').innerHTML = ''; lastBinanceAvg = null;
    } finally { hideLoader('binance_loader'); updateSpreads(); }
}

async function loadBybit() {
    const p = paramsFromUI();
    const url = '/api/bybit_rate?' + new URLSearchParams({ asset: p.asset, fiat: p.fiat, side: p.side, amount: p.amount, payments: p.payments_bybit, verified: p.verified_bybit });
    showLoader('bybit_loader');
    try {
        const res = await fetch(url); const data = await res.json();
        const e = $('bybit_error'); const ok = $('bybit_status');
        if (!data.ok) {
            e.style.display = ''; e.textContent = 'Ошибка: ' + (data.error || 'unknown'); ok.style.display = 'none';
            $('bybit_avg').textContent = '—'; $('bybit_prices').textContent = '—'; $('bybit_tbody').innerHTML = ''; lastBybitAvg = null;
        } else {
            e.style.display = 'none'; ok.style.display = '';
            const next = data.avg ?? null;
            setAnimatedText($('bybit_avg'), (next != null ? fmt(next) : '—') + ' ' + p.fiat, lastBybitAvg, next);
            $('bybit_prices').textContent = data.prices && data.prices.length ? ('#3–5: ' + data.prices.slice(2, 5).map(fmt).join(' • ')) : '—';
            const tb = $('bybit_tbody'); tb.innerHTML = '';
            (data.items || []).forEach((it, i) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${i + 1}</td><td>${it.name || '-'}</td><td>${fmt(it.price)}</td><td>${it.volume ?? '-'}</td><td>${it.min ?? '-'}</td><td>${it.max ?? '-'}</td>`;
                tb.appendChild(tr);
            });
            lastBybitAvg = next;
        }
    } catch {
        const e = $('bybit_error'); e.style.display = ''; e.textContent = 'Ошибка сети';
        $('bybit_status').style.display = 'none'; $('bybit_avg').textContent = '—'; $('bybit_prices').textContent = '—'; $('bybit_tbody').innerHTML = ''; lastBybitAvg = null;
    } finally { hideLoader('bybit_loader'); updateSpreads(); }
}

/* спреды */
function updateSpreads() {
    if (lastGfPrice != null) {
        const s1 = (lastBinanceAvg == null) ? null : ((lastBinanceAvg - lastGfPrice) / lastGfPrice * 100);
        const s2 = (lastBybitAvg == null) ? null : ((lastBybitAvg - lastGfPrice) / lastGfPrice * 100);
        $('gf_spread_bin').innerHTML = s1 == null ? '—' : ((s1 > 0 ? '+' : '') + s1.toFixed(2) + '%');
        $('gf_spread_byb').innerHTML = s2 == null ? '—' : ((s2 > 0 ? '+' : '') + s2.toFixed(2) + '%');
    }
    if (window.__lastXePrice != null) {
        const base = window.__lastXePrice;
        const s1 = (lastBinanceAvg == null) ? null : ((lastBinanceAvg - base) / base * 100);
        const s2 = (lastBybitAvg == null) ? null : ((lastBybitAvg - base) / base * 100);
        $('xe_spread_bin').innerHTML = s1 == null ? '—' : ((s1 > 0 ? '+' : '') + s1.toFixed(2) + '%');
        $('xe_spread_byb').innerHTML = s2 == null ? '—' : ((s2 > 0 ? '+' : '') + s2.toFixed(2) + '%');
    }
}

/* ===== XE ===== */
async function fillXeCodes() {
    try {
        const r = await fetch('/api/xe/codes'); const js = await r.json();
        const list = (js.codes || []).sort();
        $('xe_codes').innerHTML = ''; $('gf_codes').innerHTML = '';
        list.forEach(code => {
            const o1 = document.createElement('option'); o1.value = code; $('xe_codes').appendChild(o1);
            const o2 = document.createElement('option'); o2.value = code; $('gf_codes').appendChild(o2);
        });
        if (!$('xe_from').value) $('xe_from').value = 'USD';
        if (!$('xe_to').value) $('xe_to').value = $('fiat').value || 'UAH';
        if (!$('gf_from').value) $('gf_from').value = 'USD';
        if (!$('gf_to').value) $('gf_to').value = $('fiat').value || 'UAH';
    } catch { /* ignore */ }
}
function currentXePair() { const f = ($('xe_from').value || '').toUpperCase().trim(); const t = ($('xe_to').value || '').toUpperCase().trim(); if (!f || !t) return null; return { from: f, to: t }; }
function updateQuery(params) {
    const q = new URLSearchParams(location.search);
    Object.entries(params).forEach(([k, v]) => q.set(k, v));
    history.replaceState(null, '', `?${q.toString()}`);
}
function applyXE() { refreshXENow(); const pr = currentXePair(); if (pr) updateQuery({ xe_from: pr.from, xe_to: pr.to }); }
async function loadXE() {
    const pr = currentXePair(); const err = $('xe_error'); if (!pr) { err.style.display = ''; err.textContent = 'Укажите пары XE (From/To).'; return; }
    const url = '/api/xe?' + new URLSearchParams({ from: pr.from, to: pr.to }); showLoader('xe_loader');
    try {
        const r = await fetch(url); const js = await r.json(); $('xe_pair').textContent = `${pr.from}-${pr.to}`;
        if (!js.ok) {
            err.style.display = ''; err.textContent = 'Ошибка XE: ' + (js.error || 'unknown');
            $('xe_price').textContent = '—'; $('xe_ts').textContent = '—'; $('xe_src').textContent = '—'; $('xe_link').href = '#';
            $('xe_spread_bin').textContent = '—'; $('xe_spread_byb').textContent = '—'; window.__lastXePrice = null;
        } else {
            err.style.display = 'none'; const d = js.data; const next = d.price;
            setAnimatedText($('xe_price'), fmtSmart(next) + ' ' + pr.to, window.__lastXePrice, next);
            $('xe_ts').textContent = 'TS: ' + new Date(d.ts * 1000).toLocaleTimeString('ru-RU'); $('xe_src').textContent = d.source || 'xe'; $('xe_link').href = d.url || '#';
            window.__lastXePrice = next;
        }
    } catch {
        err.style.display = ''; err.textContent = 'Ошибка сети/парсинга XE';
        $('xe_spread_bin').textContent = '—'; $('xe_spread_byb').textContent = '—'; window.__lastXePrice = null;
    }
    finally { hideLoader('xe_loader'); updateSpreads(); }
}

/* ===== Google Finance ===== */
function currentGfPair() { const f = ($('gf_from').value || '').toUpperCase().trim(); const t = ($('gf_to').value || '').toUpperCase().trim(); if (!f || !t) return null; return { from: f, to: t }; }
function applyGF() { refreshGFNow(); const pr = currentGfPair(); if (pr) updateQuery({ gf_from: pr.from, gf_to: pr.to }); }
async function loadGF() {
    const pr = currentGfPair(); const e = $('gf_error'); if (!pr) { e.style.display = ''; e.textContent = 'Укажите пары GF (From/To).'; return; }
    $('gf_pair').textContent = `${pr.from}-${pr.to}`; const url = '/api/gf_rate?' + new URLSearchParams({ asset: pr.from, fiat: pr.to }); showLoader('gf_loader');
    try {
        const r = await fetch(url); const js = await r.json();
        if (!js.ok) {
            e.style.display = ''; e.textContent = 'GF ошибка: ' + (js.error || 'unknown');
            $('gf_price').textContent = '—'; $('gf_ts').textContent = '—'; $('gf_link').href = '#'; $('gf_spread_bin').textContent = '—'; $('gf_spread_byb').textContent = '—'; lastGfPrice = null;
        } else {
            e.style.display = 'none'; const next = js.price;
            setAnimatedText($('gf_price'), fmtShort(next) + ' ' + pr.to, lastGfPrice, next);
            $('gf_ts').textContent = 'TS: ' + new Date(js.ts * 1000).toLocaleTimeString('ru-RU'); $('gf_link').href = js.url || '#'; lastGfPrice = next;
        }
    } catch {
        e.style.display = ''; e.textContent = 'Ошибка сети/парсинга GF';
        $('gf_spread_bin').textContent = '—'; $('gf_spread_byb').textContent = '—'; lastGfPrice = null;
    }
    finally { hideLoader('gf_loader'); updateSpreads(); }
}
function refreshGFNow() { loadGF(); if (gfTimer) clearInterval(gfTimer); gfTimer = setInterval(loadGF, GF_REFRESH_MS); }

/* ===== глобальные обновления ===== */
function refreshNow() {
    loadBinance(); loadBybit();
    $('ts').textContent = '• обновлено: ' + new Date().toLocaleTimeString('ru-RU');
    if (timer) clearInterval(timer);
    timer = setInterval(() => {
        loadBinance(); loadBybit();
        $('ts').textContent = '• обновлено: ' + new Date().toLocaleTimeString('ru-RU');
    }, REFRESH_MS);
}
function refreshXENow() { loadXE(); if (xeTimer) clearInterval(xeTimer); xeTimer = setInterval(loadXE, XE_REFRESH_MS); }
function apply(ev) { ev.preventDefault(); refreshNow(); refreshXENow(); refreshGFNow(); }

/* ===== swap From/To ===== */
function swapValues(idA, idB) {
    const a = $(idA);
    const b = $(idB);
    if (!a || !b) return;
    const tmp = a.value;
    a.value = b.value;
    b.value = tmp;
}
function swapXe() { swapValues('xe_from', 'xe_to'); applyXE(); }
function swapGF() { swapValues('gf_from', 'gf_to'); applyGF(); }

/* ===== тема ===== */
function applyCurrentThemeState() {
    const root = document.documentElement;
    const mode = root.getAttribute('data-theme') || 'auto';
    let current = 'dark';
    if (mode === 'light') current = 'light'; else if (mode === 'dark') current = 'dark';
    else current = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    root.setAttribute('data-current', current);
}
function setTheme(mode) { document.documentElement.setAttribute('data-theme', mode); localStorage.setItem('p2p_theme', mode); applyCurrentThemeState(); }
function cycleTheme() { const order = ['auto', 'light', 'dark']; const curr = document.documentElement.getAttribute('data-theme') || 'auto'; const next = order[(order.indexOf(curr) + 1) % order.length]; setTheme(next); const btn = $('themeBtn'); if (btn) btn.title = `Тема: ${next}`; }

/* ===== инициализация ===== */
window.addEventListener('DOMContentLoaded', async () => {
    setTheme(localStorage.getItem('p2p_theme') || 'auto');
    $('themeBtn')?.addEventListener('click', cycleTheme);
    try { window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if ((localStorage.getItem('p2p_theme') || 'auto') === 'auto') applyCurrentThemeState(); }); } catch { }

    await fillXeCodes();

    const q = new URLSearchParams(location.search);
    const xf = q.get('xe_from'), xt = q.get('xe_to'), gfF = q.get('gf_from'), gfT = q.get('gf_to');
    if (xf) $('xe_from').value = xf; if (xt) $('xe_to').value = xt; if (gfF) $('gf_from').value = gfF; if (gfT) $('gf_to').value = gfT;

    await loadBinancePaytypes(); await loadBybitPayments(); updateCounters();

    const fiatEl = $('fiat');
    $('asset').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    fiatEl.addEventListener('change', () => {
        loadBinancePaytypes(); loadBybitPayments();
        // синхронизируем XE/GF To с выбранным фиатом
        $('xe_to').value = fiatEl.value;
        $('gf_to').value = fiatEl.value;
        refreshNow();
    });
    $('side').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    $('amount').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    $('merchant_binance')?.addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); }); // ✓ verified merchant влияет на список/выдачу
    $('verified_bybit')?.addEventListener('change', () => { refreshNow(); });

    refreshNow(); refreshXENow(); refreshGFNow();
});
