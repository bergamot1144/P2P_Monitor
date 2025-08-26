/* ====== app.js (P2P Dashboard) — минималистичное меню фильтров ====== */
/* ===== избранные платёжные методы по фиату =====
   Можно указывать ИД (identifier) И/ИЛИ человекочитаемое имя (name).
   Матчинг «умный»: по точному совпадению ИД, либо по вхождению имени (без регистра/пробелов) и синонимам.
*/
const P2P_SUPPORTED_ASSETS = new Set(['USDT', 'BTC', 'ETH', 'BNB', 'SOL', 'USDC']);

const FAVORITES_BINANCE = {
    UAH: ['MONOBANK', 'PRIVAT', 'PUMB', 'VISA', 'MASTERCARD', 'Visa/Mastercard'],
    RUB: ['SBER', 'Sberbank', 'Tinkoff', 'Тинькофф', 'Rosbank', 'Альфа', 'QIWI', 'ЮMoney', 'YooMoney', 'МИР', 'MIR'],
    KZT: ['Kaspi', 'Kaspi Bank', 'Halyk', 'Jusan', 'Forte'],
    USD: ['Wise', 'Revolut', 'SEPA', 'SWIFT', 'Bank Transfer'],
    EUR: ['SEPA', 'SWIFT', 'Wise', 'Revolut'],
    TRY: ['Ziraat', 'Vakifbank', 'Isbank', 'Garanti', 'Papara', 'FAST'],
    GEL: ['TBC', 'Bank of Georgia', 'BoG'],
    BYN: ['Belarusbank', 'Priorbank'],
    KGS: ['Optima', 'MBank', 'Demir'],
    TJS: ['Amonatbank', 'Eskhata']
};

const FAVORITES_BYBIT = {
    UAH: ['Monobank', 'PrivatBank', 'PUMB', 'Visa', 'Mastercard', 'Visa/Mastercard'],
    RUB: ['Сбербанк', 'Sberbank', 'Тинькофф', 'Tinkoff', 'МИР', 'Mir', 'QIWI', 'ЮMoney', 'YooMoney'],
    KZT: ['Kaspi', 'Kaspi Bank', 'Halyk', 'Jusan', 'Forte'],
    USD: ['Wise', 'Revolut', 'SWIFT', 'Bank Transfer'],
    EUR: ['SEPA', 'SWIFT', 'Wise', 'Revolut'],
    TRY: ['Papara', 'FAST', 'Ziraat', 'Vakifbank', 'Isbank', 'Garanti'],
    GEL: ['TBC', 'Bank of Georgia'],
    BYN: ['Belarusbank', 'Priorbank'],
    KGS: ['Optima', 'MBank', 'Demir'],
    TJS: ['Amonatbank', 'Eskhata']
};

/** USD → USDT; остальные — как есть */
function mapAssetForP2P(asset) {
    const a = String(asset || '').toUpperCase().trim();
    if (a === 'USD') return 'USDT';
    return a;
}

/** есть ли такая пара на p2p (грубо: актив из поддерживаемых и фиат — любой 3–5 буквенный код) */
function isPairSupportedOnP2P(asset, fiat) {
    const A = mapAssetForP2P(asset);
    return P2P_SUPPORTED_ASSETS.has(A) && /^[A-Z]{3,5}$/.test(String(fiat || '').toUpperCase());
}

/** хранилище референсных p2p-цен именно для пар XE/GF */
const __p2pRefs = {
    xe: { bin: null, byb: null, pair: null }, // {avg, ts} либо null
    gf: { bin: null, byb: null, pair: null },
};

/** тянем p2p AVG под конкретную пару (учитываем текущие чекбоксы/фильтры/amount/side) */
async function fetchP2PAvgForPair(exchange, asset, fiat) {
    const p = paramsFromUI(); // берём текущие side/amount/фильтры
    const A = mapAssetForP2P(asset);
    const F = String(fiat || '').toUpperCase();

    if (!isPairSupportedOnP2P(A, F)) return null;

    const qs = new URLSearchParams({
        asset: A,
        fiat: F,
        side: p.side,
        amount: p.amount,
    });

    if (exchange === 'binance') {
        if (p.merchant_binance === 'true') qs.append('merchant', 'true');
        if (p.paytypes_binance) qs.append('paytypes', p.paytypes_binance);
        const r = await fetch('/api/binance_rate?' + qs.toString());
        const js = await r.json().catch(() => null);
        if (!js || !js.ok || js.avg == null) return null;
        return Number(js.avg);
    }

    if (exchange === 'bybit') {
        if (p.verified_bybit === 'true') qs.append('verified', 'true');
        if (p.payments_bybit) qs.append('payments', p.payments_bybit);
        const r = await fetch('/api/bybit_rate?' + qs.toString());
        const js = await r.json().catch(() => null);
        if (!js || !js.ok || js.avg == null) return null;
        return Number(js.avg);
    }

    return null;
}

/** обновляем референсы p2p для панели (panel: 'xe' | 'gf') под пару {from,to} */
async function refreshP2PRefsForPanel(panel, pair) {
    const from = (pair?.from || '').toUpperCase();
    const to = (pair?.to || '').toUpperCase();
    __p2pRefs[panel].pair = `${from}-${to}`;

    if (!isPairSupportedOnP2P(from, to)) {
        __p2pRefs[panel].bin = null;
        __p2pRefs[panel].byb = null;
        return;
    }
    try {
        const [bin, byb] = await Promise.all([
            fetchP2PAvgForPair('binance', from, to),
            fetchP2PAvgForPair('bybit', from, to),
        ]);
        __p2pRefs[panel].bin = (bin != null ? Number(bin) : null);
        __p2pRefs[panel].byb = (byb != null ? Number(byb) : null);
    } catch {
        __p2pRefs[panel].bin = __p2pRefs[panel].bin ?? null;
        __p2pRefs[panel].byb = __p2pRefs[panel].byb ?? null;
    }
}

/** показать спреды для панели относительно уже загруженных p2p-референсов */
function showSpreadsForPanel(panel, basePrice) {
    const refs = __p2pRefs[panel];
    const fmtPct = (p) => (p > 0 ? '+' : '') + p.toFixed(2) + '%';

    if (panel === 'xe') {
        if (basePrice == null) { xe_spread_bin.textContent = 'N/A'; xe_spread_byb.textContent = 'N/A'; return; }
        xe_spread_bin.textContent = (refs.bin == null) ? 'N/A' : fmtPct((refs.bin - basePrice) / basePrice * 100);
        xe_spread_byb.textContent = (refs.byb == null) ? 'N/A' : fmtPct((refs.byb - basePrice) / basePrice * 100);
    } else {
        if (basePrice == null) { gf_spread_bin.textContent = 'N/A'; gf_spread_byb.textContent = 'N/A'; return; }
        gf_spread_bin.textContent = (refs.bin == null) ? 'N/A' : fmtPct((refs.bin - basePrice) / basePrice * 100);
        gf_spread_byb.textContent = (refs.byb == null) ? 'N/A' : fmtPct((refs.byb - basePrice) / basePrice * 100);
    }
}


/* нормализация для сравнения */
function _norm(s) { return String(s || '').toLowerCase().replace(/\s+/g, ''); }

/* проверка «избранности» элемента относительно текущего фиата */
function isFavoriteForFiat(ddId, item) {
    const fiat = (document.getElementById('fiat')?.value || '').toUpperCase();
    const list = ddId === 'dd_binance' ? (FAVORITES_BINANCE[fiat] || []) : (FAVORITES_BYBIT[fiat] || []);
    if (!list.length) return -1;

    const idN = _norm(item.id);
    const nameN = _norm(item.name);

    // точное совпадение по id сначала
    let idx = list.findIndex(f => _norm(f) === idN);
    if (idx >= 0) return idx;

    // затем синонимы/вхождения по имени
    idx = list.findIndex(f => {
        const fN = _norm(f);
        return nameN.includes(fN) || idN.includes(fN);
    });
    return idx; // -1 если не нашли
}

/* сортировка: избранные идут первыми, сохраняя их относительный порядок из списка FAVORITES; остальные — по имени */
function sortFavoritesFirst(ddId, arr) {
    const fav = [];
    const rest = [];
    arr.forEach(it => (isFavoriteForFiat(ddId, it) >= 0 ? fav.push(it) : rest.push(it)));

    fav.sort((a, b) => isFavoriteForFiat(ddId, a) - isFavoriteForFiat(ddId, b));
    rest.sort((a, b) => String(a.name || a.id || '').localeCompare(String(b.name || b.id || ''), 'ru', { sensitivity: 'base' }));
    return [...fav, ...rest];
}

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

/* ===== простые форматтеры ===== */
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

/* ===== раскрытие блоков фильтров (контейнеры) ===== */
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

/* =======================================================================
   МИНИМАЛИСТИЧНОЕ ВЫПАДАЮЩЕЕ МЕНЮ «Платёжные методы» (портал в body)
   ======================================================================= */

/** создаёт (однократно) оверлей и контейнер в body */
function ensurePortal() {
    if ($('__mdrop_portal')) return;

    const overlay = document.createElement('div');
    overlay.id = '__mdrop_overlay';
    Object.assign(overlay.style, {
        position: 'fixed', inset: '0', background: 'rgba(0,0,0,.35)',
        zIndex: '2147483646', display: 'none', backdropFilter: 'blur(1px)'
    });
    document.body.appendChild(overlay);

    const portal = document.createElement('div');
    portal.id = '__mdrop_portal';
    Object.assign(portal.style, {
        position: 'fixed', zIndex: '2147483647', display: 'none'
    });
    document.body.appendChild(portal);

    // закрытие по клику на затемнение
    overlay.addEventListener('click', closeAllDropdowns);
}

/** строит лаконичное меню (голая разметка без внешнего CSS) */
function buildMenuSkeleton(ddId, triggerRect, maxWidth = 520) {
    ensurePortal();

    const overlay = $('__mdrop_overlay');
    const portal = $('__mdrop_portal');
    portal.innerHTML = ''; // очистить

    // Корневая «карточка» меню
    const menu = document.createElement('div');
    menu.className = 'mdrop-fly';
    Object.assign(menu.style, {
        position: 'fixed',
        top: Math.min(triggerRect.bottom + 6, window.innerHeight - 16) + 'px',
        left: Math.max(8, Math.min(triggerRect.left, window.innerWidth - maxWidth - 8)) + 'px',
        width: Math.min(maxWidth, Math.max(320, triggerRect.width)) + 'px',
        maxHeight: '420px',
        background: 'var(--bg2, #0e1219)',
        border: '1px solid var(--border, #242a36)',
        borderRadius: '12px',
        boxShadow: '0 10px 30px rgba(0,0,0,.35)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
    });

    // Head: поиск
    const head = document.createElement('div');
    Object.assign(head.style, {
        position: 'sticky', top: '0',
        background: 'inherit',
        borderBottom: '1px solid var(--border, #242a36)',
        padding: '8px'
    });
    const input = document.createElement('input');
    input.id = ddId + '_search';
    input.placeholder = 'Поиск метода...';
    Object.assign(input.style, {
        width: '100%', padding: '10px 12px',
        borderRadius: '10px', border: '1px solid var(--border, #242a36)',
        background: 'var(--bg, #0b0d12)', color: 'var(--fg, #e6e9ef)'
    });
    head.appendChild(input);
    menu.appendChild(head);

    // Body: сетка 2 колонки
    const body = document.createElement('div');
    body.className = 'mdrop-body';
    Object.assign(body.style, {
        padding: '10px', overflow: 'auto', flex: '1 1 auto'
    });

    const grid = document.createElement('div');
    grid.id = ddId === 'dd_binance' ? 'dd_binance_grid' : 'dd_bybit_grid';
    Object.assign(grid.style, {
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '8px 10px',
        alignItems: 'stretch'
    });
    body.appendChild(grid);
    menu.appendChild(body);

    // Foot: кнопки
    const foot = document.createElement('div');
    Object.assign(foot.style, {
        position: 'sticky', bottom: '0',
        display: 'flex', gap: '8px', justifyContent: 'flex-end',
        padding: '8px',
        background: 'inherit',
        borderTop: '1px solid var(--border, #242a36)'
    });

    const okBtn = document.createElement('button');
    okBtn.className = 'js-confirm';
    okBtn.textContent = 'Подтвердить';
    Object.assign(okBtn.style, buttonStyle(true));

    const resetBtn = document.createElement('button');
    resetBtn.className = 'js-reset';
    resetBtn.textContent = 'Сбросить';
    Object.assign(resetBtn.style, buttonStyle(false));

    foot.appendChild(okBtn);
    foot.appendChild(resetBtn);
    menu.appendChild(foot);

    portal.appendChild(menu);

    // показать
    overlay.style.display = 'block';
    portal.style.display = 'block';

    // обработка кликов
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

    // поиск
    input.addEventListener('input', () => {
        searchState[ddId] = (input.value || '').toLowerCase().trim();
        renderDropdownOptions(ddId);
    });
    // фокус сразу
    setTimeout(() => input.focus(), 0);

    return { menu, grid, input };
}

function buttonStyle(primary) {
    return {
        padding: '8px 12px',
        borderRadius: '10px',
        border: '1px solid var(--border, #242a36)',
        background: primary ? 'rgb(26,78,51)' : 'rgba(255,255,255,0.02)',
        color: 'var(--fg, #e6e9ef)',
        cursor: 'pointer',
        fontSize: '12px'
    };
}

/** открывает меню у конкретного дропа */
/* ==== надёжное открытие: портал поверх страницы + фолбэк на встроенное меню ==== */
// ... ваша функция
function mdropToggle(ddId) {
    try {
        const dd = document.getElementById(ddId);
        if (!dd) return;
        const trigger = dd.querySelector('.mdrop-btn') || dd;

        // если уже открыто — закрываем
        if (dd.classList.contains('open')) { closeAllDropdowns(); return; }

        // синхронизируем временный выбор
        tempSelected[ddId] = new Set([...(ddId === 'dd_binance' ? selectedBinance : selectedBybit)]);

        closeAllDropdowns();
        dd.classList.add('open');
        const card = dd.closest('.card'); if (card) card.classList.add('raised');

        // пробуем показать портал-меню
        const rect = trigger.getBoundingClientRect();
        const built = buildMenuSkeleton(ddId, rect);
        if (!built) throw new Error('portal-not-built');

        renderDropdownOptions(ddId);
        window.addEventListener('keydown', escCloser, true);
        window.addEventListener('resize', closeAllDropdowns, true);
        window.addEventListener('scroll', (e) => {
            // если скроллится именно выпадашка (.mdrop-fly или её содержимое) — не закрываем
            if (e.target.closest && e.target.closest('.mdrop-fly')) {
                return;
            }
            closeAllDropdowns();
        }, true);
    } catch (err) {
        console.error('mdropToggle error:', err);
        // фолбэк на встроенное меню под кнопкой
        openInline(ddId);
    }
}

// ДЕЛАЕМ ФУНКЦИЮ ГЛОБАЛЬНОЙ ДЛЯ inline onclick=
window.mdropToggle = mdropToggle;
// Делегированный клик по любой кнопке .mdrop-btn — даже если inline-обработчик не отработал
document.addEventListener('click', function (e) {
    const btn = e.target.closest('.mdrop-btn');
    if (!btn) return;
    const root = btn.closest('.mdrop');
    if (!root || !root.id) return;
    e.preventDefault();
    e.stopPropagation();
    try {
        mdropToggle(root.id);
    } catch (err) {
        console.error('delegated mdrop click failed:', err);
    }
}, true);
function openInline(ddId) {
    const root = document.getElementById(ddId);
    const menu = root?.querySelector('.mdrop-menu');
    if (!menu) return;
    menu.style.display = 'flex';

    const input = document.getElementById(ddId + '_search');
    if (input) {
        input.value = searchState[ddId] || '';
        input.oninput = () => {
            searchState[ddId] = (input.value || '').toLowerCase().trim();
            renderDropdownOptions(ddId);
        };
        setTimeout(() => input.focus(), 0);
    }

    // кнопки подтверждения/сброса
    if (!menu.__wired) {
        menu.addEventListener('click', (e) => {
            e.stopPropagation();
            if (e.target.closest('.js-confirm')) {
                if (ddId === 'dd_binance') selectedBinance = new Set([...tempSelected[ddId]]);
                if (ddId === 'dd_bybit') selectedBybit = new Set([...tempSelected[ddId]]);
                updateCounters(); refreshNow(); closeAllDropdowns(); return;
            }
            if (e.target.closest('.js-reset')) {
                tempSelected[ddId] = new Set(); renderDropdownOptions(ddId);
                const cnt = document.getElementById(ddId === 'dd_binance' ? 'dd_binance_count' : 'dd_bybit_count');
                if (cnt) cnt.textContent = '0';
            }
        });
        menu.__wired = true;
    }

    renderDropdownOptions(ddId);
}


function escCloser(e) { if (e.key === 'Escape') closeAllDropdowns(); }

function openInline(ddId) {
    const root = document.getElementById(ddId);
    const menu = root?.querySelector('.mdrop-menu');
    if (!menu) return;
    menu.style.display = 'flex';

    // поиск
    const input = document.getElementById(ddId + '_search');
    if (input) {
        input.value = searchState[ddId] || '';
        input.oninput = () => {
            searchState[ddId] = (input.value || '').toLowerCase().trim();
            renderDropdownOptions(ddId);
        };
    }
    // кнопки
    wireInlineMenu(ddId);
    // плитки
    renderDropdownOptions(ddId);
}

function wireInlineMenu(ddId) {
    const root = document.getElementById(ddId);
    const menu = root?.querySelector('.mdrop-menu');
    if (!menu || menu.__wired) return;

    menu.addEventListener('click', (e) => {
        e.stopPropagation();
        if (e.target.closest('.js-confirm')) {
            if (ddId === 'dd_binance') selectedBinance = new Set([...tempSelected[ddId]]);
            if (ddId === 'dd_bybit') selectedBybit = new Set([...tempSelected[ddId]]);
            updateCounters(); refreshNow(); closeAllDropdowns(); return;
        }
        if (e.target.closest('.js-reset')) {
            tempSelected[ddId] = new Set(); renderDropdownOptions(ddId);
            const cnt = document.getElementById(ddId === 'dd_binance' ? 'dd_binance_count' : 'dd_bybit_count');
            if (cnt) cnt.textContent = '0';
        }
    });
    menu.__wired = true;
}

/* универсальная отрисовка плиток: сначала ищем грид в портале, иначе — во встроенном меню */
function renderDropdownOptions(ddId) {
    const isBin = ddId === 'dd_binance';
    const items = filteredItems(ddId);
    const portal = document.getElementById('__mdrop_portal');
    const portalGrid = portal?.querySelector('#' + (isBin ? 'dd_binance_grid' : 'dd_bybit_grid'));
    const inlineGrid = document.getElementById(isBin ? 'dd_binance_grid' : 'dd_bybit_grid');
    const grid = portalGrid || inlineGrid;
    if (!grid) return;

    grid.innerHTML = '';
    const temp = tempSelected[ddId];

    items.forEach(it => {
        const id = String(it.id), name = it.name || id;
        const pill = document.createElement('div');
        pill.className = 'mdrop-pill' + (temp.has(id) ? ' active' : '');
        pill.textContent = name;
        pill.title = name;
        pill.addEventListener('click', () => {
            if (temp.has(id)) temp.delete(id); else temp.add(id);
            pill.classList.toggle('active');
            const cnt = document.getElementById(isBin ? 'dd_binance_count' : 'dd_bybit_count');
            if (cnt) cnt.textContent = String(temp.size);
        });
        grid.appendChild(pill);
    });

    const cnt = document.getElementById(isBin ? 'dd_binance_count' : 'dd_bybit_count');
    if (cnt) cnt.textContent = String(temp.size);
}

/* закрыть всё: и портал, и встроенные меню */
function closeAllDropdowns() {
    // встроенные
    document.querySelectorAll('.mdrop .mdrop-menu').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.mdrop.open').forEach(dd => {
        dd.classList.remove('open');
        const card = dd.closest('.card'); if (card) card.classList.remove('raised');
    });

    // портал
    const overlay = document.getElementById('__mdrop_overlay');
    const portal = document.getElementById('__mdrop_portal');
    if (overlay) overlay.style.display = 'none';
    if (portal) { portal.style.display = 'none'; portal.innerHTML = ''; }

    window.removeEventListener('keydown', escCloser, true);
    window.removeEventListener('resize', closeAllDropdowns, true);
    window.removeEventListener('scroll', closeAllDropdowns, true);
}


/* ===== логика плиток и поиска ===== */
function filteredItems(ddId) {
    const list = (ddId === 'dd_binance') ? binanceItems : bybitItems;
    const q = (searchState[ddId] || '').toLowerCase().trim();
    let arr = list;
    if (q) {
        arr = list.filter(it => (String(it.name || '') + ' ' + String(it.id || '')).toLowerCase().includes(q));
    }
    return sortFavoritesFirst(ddId, arr);
}

function renderDropdownOptions(ddId) {
    const isBin = ddId === 'dd_binance';
    const list = filteredItems(ddId);
    const portal = $('__mdrop_portal');
    if (!portal) return;
    const grid = portal.querySelector('#' + (isBin ? 'dd_binance_grid' : 'dd_bybit_grid'));
    if (!grid) return;
    grid.innerHTML = '';

    const temp = tempSelected[ddId];

    list.forEach(it => {
        const id = String(it.id);
        const name = it.name || id;

        const isFavIdx = isFavoriteForFiat(ddId, it);
        const pill = document.createElement('div');
        pill.className = 'mdrop-pill' + (temp.has(id) ? ' active' : '') + (isFavIdx >= 0 ? ' fav' : '');
        pill.innerHTML = (isFavIdx >= 0 ? '<span class="fav-star" title="Избранный метод">★</span>' : '') +
            '<span class="pill-title"></span>';
        pill.querySelector('.pill-title').textContent = name;

        Object.assign(pill.style, pillStyle(temp.has(id)));
        pill.title = name;

        pill.addEventListener('click', () => {
            if (temp.has(id)) temp.delete(id); else temp.add(id);
            Object.assign(pill.style, pillStyle(temp.has(id)));
            const cnt = $(isBin ? 'dd_binance_count' : 'dd_bybit_count');
            if (cnt) cnt.textContent = String(temp.size);
        });

        grid.appendChild(pill);
    });

    const cnt = $(isBin ? 'dd_binance_count' : 'dd_bybit_count');
    if (cnt) cnt.textContent = String(temp.size);
}

function pillStyle(active) {
    return {
        minHeight: '34px',
        padding: '6px 10px',
        borderRadius: '10px',
        border: '1px solid ' + (active ? 'color-mix(in oklab, var(--accent, #22c55e) 80%, var(--border, #242a36))' : 'var(--border, #242a36)'),
        background: active
            ? 'color-mix(in oklab, var(--bg2, #0e1219) 70%, var(--accent, #22c55e) 18%)'
            : 'var(--bg2, #0e1219)',
        color: 'var(--fg, #e6e9ef)',
        fontSize: '12px',
        display: 'flex',
        alignItems: 'center',
        cursor: 'pointer',
        userSelect: 'none',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis'
    };
}

function updateCounters() {
    $('dd_binance_count').textContent = String(selectedBinance.size);
    $('dd_bybit_count').textContent = String(selectedBybit.size);
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
    const url = '/api/binance_rate?' + new URLSearchParams({
        asset: p.asset, fiat: p.fiat, side: p.side, amount: p.amount,
        paytypes: p.paytypes_binance, merchant: p.merchant_binance
    });
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
    const url = '/api/bybit_rate?' + new URLSearchParams({
        asset: p.asset, fiat: p.fiat, side: p.side, amount: p.amount,
        payments: p.payments_bybit, verified: p.verified_bybit
    });
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

/* ===== спреды ===== */
//function updateSpreads() {
//    if (lastGfPrice != null) {
//        const s1 = (lastBinanceAvg == null) ? null : ((lastBinanceAvg - lastGfPrice) / lastGfPrice * 100);
//        const s2 = (lastBybitAvg == null) ? null : ((lastBybitAvg - lastGfPrice) / lastGfPrice * 100);
//        $('gf_spread_bin').innerHTML = s1 == null ? '—' : ((s1 > 0 ? '+' : '') + s1.toFixed(2) + '%');
//        $('gf_spread_byb').innerHTML = s2 == null ? '—' : ((s2 > 0 ? '+' : '') + s2.toFixed(2) + '%');
//    }
//    if (window.__lastXePrice != null) {
//        const base = window.__lastXePrice;
//        const s1 = (lastBinanceAvg == null) ? null : ((lastBinanceAvg - base) / base * 100);
//        const s2 = (lastBybitAvg == null) ? null : ((lastBybitAvg - base) / base * 100);
//        $('xe_spread_bin').innerHTML = s1 == null ? '—' : ((s1 > 0 ? '+' : '') + s1.toFixed(2) + '%');
//        $('xe_spread_byb').innerHTML = s2 == null ? '—' : ((s2 > 0 ? '+' : '') + s2.toFixed(2) + '%');
//    }
//}
function updateSpreads() {
    // намеренно пусто — функцию оставили, чтобы не ломать вызовы.
    // Спреды теперь обновляются в showSpreadsForPanel из loadXE/loadGF.
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
    const pr = currentXePair();
    const err = $('xe_error');
    if (!pr) { err.style.display = ''; err.textContent = 'Укажите пары XE (From/To).'; return; }

    const url = '/api/xe?' + new URLSearchParams({ from: pr.from, to: pr.to });
    showLoader('xe_loader');

    try {
        const r = await fetch(url);
        const js = await r.json();
        $('xe_pair').textContent = `${pr.from}-${pr.to}`;

        if (js.ok) {
            // УСПЕХ
            err.style.display = 'none';
            const d = js.data;
            const next = d.price;

            setAnimatedText($('xe_price'), fmtSmart(next) + ' ' + pr.to, window.__lastXePrice, next);
            $('xe_ts').textContent = 'TS: ' + new Date(d.ts * 1000).toLocaleTimeString('ru-RU');
            $('xe_src').textContent = d.source || 'xe';
            $('xe_link').href = d.url || '#';
            window.__lastXePrice = next;

            // подтягиваем p2p-референсы под ЭТУ ЖЕ пару и рисуем спреды
            await refreshP2PRefsForPanel('xe', pr);
            showSpreadsForPanel('xe', next);
        } else {
            // ОШИБКА ОТ БЭКЕНДА
            err.style.display = '';
            err.textContent = 'Ошибка XE: ' + (js.error || 'unknown');
            $('xe_price').textContent = '—';
            $('xe_ts').textContent = '—';
            $('xe_src').textContent = '—';
            $('xe_link').href = '#';
            $('xe_spread_bin').textContent = 'N/A';
            $('xe_spread_byb').textContent = 'N/A';
            window.__lastXePrice = null;
        }
    } catch {
        // СЕТЕВАЯ/ПАРСИНГ-ОШИБКА
        err.style.display = '';
        err.textContent = 'Ошибка сети/парсинга XE';
        $('xe_price').textContent = '—';
        $('xe_ts').textContent = '—';
        $('xe_src').textContent = '—';
        $('xe_link').href = '#';
        $('xe_spread_bin').textContent = 'N/A';
        $('xe_spread_byb').textContent = 'N/A';
        window.__lastXePrice = null;
    } finally {
        hideLoader('xe_loader');
        updateSpreads(); // теперь пустышка — оставлена для совместимости
    }
}
/* ===== Google Finance ===== */
function currentGfPair() { const f = ($('gf_from').value || '').toUpperCase().trim(); const t = ($('gf_to').value || '').toUpperCase().trim(); if (!f || !t) return null; return { from: f, to: t }; }
function applyGF() { refreshGFNow(); const pr = currentGfPair(); if (pr) updateQuery({ gf_from: pr.from, gf_to: pr.to }); }
async function loadGF() {
    const pr = currentGfPair();
    const e = $('gf_error');
    if (!pr) { e.style.display = ''; e.textContent = 'Укажите пары GF (From/To).'; return; }

    $('gf_pair').textContent = `${pr.from}-${pr.to}`;
    const url = '/api/gf_rate?' + new URLSearchParams({ asset: pr.from, fiat: pr.to });
    showLoader('gf_loader');

    try {
        const r = await fetch(url);
        const js = await r.json();

        if (js.ok) {
            // УСПЕХ
            e.style.display = 'none';
            const next = js.price;

            setAnimatedText($('gf_price'), fmtShort(next) + ' ' + pr.to, lastGfPrice, next);
            $('gf_ts').textContent = 'TS: ' + new Date(js.ts * 1000).toLocaleTimeString('ru-RU');
            $('gf_link').href = js.url || '#';
            lastGfPrice = next;

            await refreshP2PRefsForPanel('gf', pr);
            showSpreadsForPanel('gf', next);
        } else {
            // ОШИБКА ОТ БЭКЕНДА
            e.style.display = '';
            e.textContent = 'GF ошибка: ' + (js.error || 'unknown');
            $('gf_price').textContent = '—';
            $('gf_ts').textContent = '—';
            $('gf_link').href = '#';
            $('gf_spread_bin').textContent = 'N/A';
            $('gf_spread_byb').textContent = 'N/A';
            lastGfPrice = null;
        }
    } catch {
        // СЕТЕВАЯ/ПАРСИНГ-ОШИБКА
        e.style.display = '';
        e.textContent = 'Ошибка сети/парсинга GF';
        $('gf_price').textContent = '—';
        $('gf_ts').textContent = '—';
        $('gf_link').href = '#';
        $('gf_spread_bin').textContent = 'N/A';
        $('gf_spread_byb').textContent = 'N/A';
        lastGfPrice = null;
    } finally {
        hideLoader('gf_loader');
        updateSpreads();
    }
} function refreshGFNow() { loadGF(); if (gfTimer) clearInterval(gfTimer); gfTimer = setInterval(loadGF, GF_REFRESH_MS); }

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
        $('xe_to').value = fiatEl.value;
        $('gf_to').value = fiatEl.value;
        refreshNow();
    });
    $('side').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    $('amount').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    $('merchant_binance')?.addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    $('verified_bybit')?.addEventListener('change', () => { refreshNow(); });

    // клики на кнопках «Платёжные методы»
    // (если используете свои обработчики onclick в HTML — оставьте их,
    //  этот блок — на всякий случай)
    ['dd_binance', 'dd_bybit'].forEach(id => {
        const dd = $(id);
        const btn = dd?.querySelector('.mdrop-btn');
        if (btn) btn.addEventListener('click', (e) => { e.stopPropagation(); mdropToggle(id); });
    });

    refreshNow(); refreshXENow(); refreshGFNow();
});
