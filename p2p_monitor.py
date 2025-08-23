# p2p_dashboard.py
# Flask-дэшборд: Binance • Bybit • Google Finance • XE (универсальные пары, устойчивый парсинг больших чисел)

import os
import re
import json
import time
from decimal import Decimal, InvalidOperation, getcontext
from typing import Optional, Tuple, List, Dict
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template

# ---- Playwright (мягкий импорт; если нет — XE работает через requests-фоллбек)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    PLAYWRIGHT_OK = True
except Exception:
    PLAYWRIGHT_OK = False

# Точность Decimal для длинных значений (BTC→KZT и т.п.)
getcontext().prec = 28

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

if not TEMPLATE_DIR.exists():
    TEMPLATE_DIR = Path.cwd() / "templates"
if not STATIC_DIR.exists():
    STATIC_DIR = Path.cwd() / "static"

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
app.config["JSON_AS_ASCII"] = False

@app.route("/")
def index():
    return render_template("index.html")

# ====================== Заголовки/куки P2P ======================
BINANCE_COOKIE = os.getenv("BINANCE_COOKIE", "")
BYBIT_COOKIE   = os.getenv("BYBIT_COOKIE", "")

BINANCE_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
BYBIT_URL   = "https://www.bybit.com/x-api/fiat/otc/item/online"

BINANCE_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "ru-RU,ru;q=0.9",
    "content-type": "application/json",
    "origin": "https://p2p.binance.com",
    "referer": "https://p2p.binance.com/ru-RU",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
}
if BINANCE_COOKIE:
    BINANCE_HEADERS["cookie"] = BINANCE_COOKIE

BYBIT_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://www.bybit.com",
    "referer": "https://www.bybit.com/ru-RU/p2p",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
}
if BYBIT_COOKIE:
    BYBIT_HEADERS["cookie"] = BYBIT_COOKIE

# ====================== Устойчивое извлечение чисел ===========================
# Разделители тысяч: пробел, NBSP, узкий NBSP, запятая; десятичный: . или ,
NUMBER_RE = re.compile(r"(?:\d{1,3}(?:[,   ]\d{3})+|\d+)(?:[.,]\d+)?")

def _normalize_number_string(s: str) -> str:
    """Нормализует строку числа к стандартному виду для Decimal."""
    s = (s or "").strip()
    # NBSP/узкий NBSP → обычный пробел → убрать все пробелы
    s = s.replace("\u00A0", " ").replace("\u202F", " ")
    s = re.sub(r"\s+", "", s)

    has_comma = "," in s
    has_dot   = "." in s

    if has_comma and has_dot:
        # Правый символ — десятичный
        last_comma = s.rfind(",")
        last_dot   = s.rfind(".")
        if last_dot > last_comma:
            # десятичная точка, запятые — тысячные
            s = s.replace(",", "")
        else:
            # десятичная запятая, точки — тысячные
            s = s.replace(".", "")
            s = s.replace(",", ".")
        return s

    if has_comma:
        if s.count(",") > 1:
            # Несколько запятых: попробуем последнюю как десятичную, остальные — тысячные
            pos = s.rfind(",")
            left = s[:pos].replace(",", "")
            right = s[pos+1:]
            s = left + "." + right
        else:
            # Одна запятая — считаем её десятичной
            s = s.replace(",", ".")
        return s

    if has_dot:
        if s.count(".") > 1:
            # Несколько точек:
            parts = s.split(".")
            # Проверим «чистые тысячные» (все группы по 3, первая ≤3)
            if all(i == 0 or len(p) == 3 for i, p in enumerate(parts)) and len(parts[-1]) == 3:
                # 1.234.567 → 1234567
                s = "".join(parts)
            else:
                # Последняя — десятичная, остальные — тысячные
                pos = s.rfind(".")
                left = s[:pos].replace(".", "")
                right = s[pos+1:]
                s = left + "." + right
        else:
            # Одна точка — всегда десятичная
            # (исправление: НЕ удаляем точку даже если после неё 3 цифры)
            pass
        return s

    # Нет разделителей — вернём как есть
    return s

def to_decimal(num_str: str) -> Decimal:
    s = _normalize_number_string(num_str)
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(0)

def best_decimal_from_text(text: str) -> Optional[Decimal]:
    """
    Находит «лучшее» число в тексте:
    - выбираем совпадение с максимальным количеством цифр (чтобы брать 4,795,807.00, а не «1»);
    - затем нормализуем и конвертируем в Decimal.
    """
    matches = list(NUMBER_RE.finditer(text or ""))
    if not matches:
        return None
    def size_key(m):
        raw = m.group(0)
        digits_only = re.sub(r"[^\d]", "", raw)
        return (len(digits_only), len(raw))  # сначала по числу цифр, потом по общей длине
    m = max(matches, key=size_key)
    return to_decimal(m.group(0))

# ====================== Вспомогалки ===========================
def _avg_3_5(prices: List[Decimal]) -> Optional[Decimal]:
    if len(prices) >= 5:
        return (prices[2] + prices[3] + prices[4]) / Decimal(3)
    return None

def _d(x) -> Optional[Decimal]:
    try:
        if x is None:
            return None
        if isinstance(x, Decimal):
            return x
        return to_decimal(str(x))
    except Exception:
        return None

# ====================== Google Finance ==========================
GF_HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

def _gf_price_direct(asset: str, fiat: str) -> Tuple[Decimal, str]:
    A, F = asset.upper(), fiat.upper()
    url  = f"https://www.google.com/finance/quote/{A}-{F}"
    r = requests.get(url, headers=GF_HEADERS, timeout=12)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    blk = soup.select_one(f'div[jscontroller="NdbN0c"][jsname="AS5Pxb"][data-source="{A}"][data-target="{F}"]')
    if blk and blk.has_attr("data-last-price"):
        return (to_decimal(blk["data-last-price"]), url)

    node = soup.select_one("div.YMlKec.fxKbKc") or soup.select_one("div.YMlKec")
    if node and node.text:
        val = best_decimal_from_text(node.get_text(" ", strip=True))
        if val is not None:
            return (val, url)

    m = re.findall(r'data-last-price="([^"]+)"', r.text)
    if m:
        return (to_decimal(m[-1]), url)

    raise RuntimeError("GF: не удалось извлечь цену")

def fetch_gf(asset: str, fiat: str) -> Dict:
    p, url = _gf_price_direct(asset, fiat)
    return {"pair": f"{asset.upper()}-{fiat.upper()}", "price": float(p), "url": url, "ts": int(time.time())}

# ====================== Binance ================================
def fetch_binance(asset="USDT", fiat="UAH", side="SELL", pay_types=None, amount="20000", rows=10, merchant=True, page=1):
    payload = {
        "asset": asset, "fiat": fiat, "merchantCheck": bool(merchant),
        "page": int(page), "payTypes": list(pay_types or []),
        "publisherType": None, "rows": int(rows),
        "tradeType": side, "transAmount": str(amount),
    }
    r = requests.post(BINANCE_URL, headers=BINANCE_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    js = r.json()
    if js.get("code") != "000000" or "data" not in js:
        raise RuntimeError(f"Binance API error: {js}")
    data = js["data"] or []
    items, prices = [], []
    for ad in data[:5]:
        adv = ad.get("adv") or {}
        seller = (ad.get("advertiser") or {}).get("nickName") or "-"
        price  = _d(adv.get("price"))
        if price is None:
            continue
        items.append({
            "name": seller,
            "price": float(price),
            "min": adv.get("minSingleTransAmount"),
            "max": adv.get("maxSingleTransAmount"),
            "volume": adv.get("surplusAmount"),
        })
        prices.append(price)
    avg = _avg_3_5(prices)
    return {"items": items, "prices": [float(x) for x in prices], "avg": (float(avg) if avg is not None else None)}

def discover_binance_paytypes(asset="USDT", fiat="UAH", side="SELL", amount="20000", merchant=True, pages=2, rows=20):
    seen = {}
    for p in range(1, pages+1):
        payload = {
            "asset": asset, "fiat": fiat, "merchantCheck": bool(merchant),
            "page": p, "payTypes": [], "publisherType": None,
            "rows": int(rows), "tradeType": side, "transAmount": str(amount),
        }
        r = requests.post(BINANCE_URL, headers=BINANCE_HEADERS, json=payload, timeout=15)
        if r.status_code != 200:
            break
        js = r.json()
        if js.get("code") != "000000":
            break
        data = js.get("data", []) or []
        if not data:
            break
        for ad in data:
            adv = ad.get("adv", {}) or {}
            for tm in adv.get("tradeMethods", []) or []:
                ident = (tm.get("identifier") or tm.get("payType") or "").strip()
                name  = (tm.get("tradeMethodName") or tm.get("name") or ident).strip()
                if ident:
                    seen[ident] = name
            for ident in ad.get("payTypes", []) or []:
                if ident and ident not in seen:
                    seen[ident] = ident
    items = [{"id": k, "name": v} for k, v in seen.items()]
    items.sort(key=lambda x: (x["name"].lower(), x["id"]))
    return items

# ====================== Bybit ================================
def fetch_bybit(token="USDT", fiat="UAH", side="SELL", payments=None, amount="20000", rows=10, verified=False):
    side_map = {"SELL": "0", "BUY": "1"}
    payload = {
        "tokenId": token, "currencyId": fiat, "payment": payments or [],
        "side": side_map.get(side.upper(), "1"),
        "size": str(rows), "page": "1",
        "amount": str(amount), "authMaker": bool(verified),
        "canTrade": False, "shieldMerchant": False, "reputation": False, "country": ""
    }
    r = requests.post(BYBIT_URL, headers=BYBIT_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    js = r.json()
    result = js.get("result", {}) if isinstance(js, dict) else {}
    data = (result.get("items") or [])[:5]

    items, prices = [], []
    for ad in data:
        name  = ad.get("nickName") or "-"
        price = _d(ad.get("price"))
        if price is None:
            continue
        items.append({
            "name": name,
            "price": float(price),
            "min": ad.get("minAmount"),
            "max": ad.get("maxAmount"),
            "volume": ad.get("lastQuantity"),
        })
        prices.append(price)
    avg = _avg_3_5(prices)
    return {"items": items, "prices": [float(x) for x in prices], "avg": (float(avg) if avg is not None else None)}

# ====================== XE (универсальный) =====================
XE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
NAV_TIMEOUT = 15000
SEL_TIMEOUT = 6000

XE_STABLES = {"USDT", "USDC", "DAI", "TUSD", "EURC", "USDP"}

def xe_extract_both(soup: BeautifulSoup, frm: str, to: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    conv_val = None
    chart_val = None
    # conversion box
    for box in soup.select("div[data-testid='conversion']"):
        header_p = None
        for p in box.find_all("p"):
            if p.get_text(" ", strip=True).endswith("="):
                header_p = p
                break
        if header_p is not None:
            value_p = header_p.find_next_sibling("p")
            if value_p is not None:
                conv_val = best_decimal_from_text(value_p.get_text("", strip=True) or "")
                break
    # chart table
    for p in soup.select("section[data-testid='currency-conversion-chart-stats-table'] p"):
        chart_val_candidate = best_decimal_from_text(p.get_text(" ", strip=True) or "")
        if chart_val_candidate:
            chart_val = chart_val_candidate
            break
    return conv_val, chart_val

def xe_extract_meta(soup: BeautifulSoup) -> Optional[Decimal]:
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    if not meta:
        return None
    return best_decimal_from_text(meta.get("content") or "")

def fetch_xe_via_browser(frm: str, to: str, amount: Decimal = Decimal(1)) -> Tuple[Optional[Decimal], str, Dict]:
    url = f"https://www.xe.com/currencyconverter/convert/?Amount={amount}&From={frm}&To={to}"
    if not PLAYWRIGHT_OK:
        return None, url, {"note": "playwright_not_installed"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            locale="ru-RU",
            user_agent=XE_UA,
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        page = context.new_page()
        hydrated = False
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            try:
                page.wait_for_selector(
                    "div[data-testid='conversion'] p, section[data-testid='currency-conversion-chart-stats-table'] p, meta[property='og:description']",
                    timeout=SEL_TIMEOUT
                )
                hydrated = True
            except PWTimeoutError:
                pass
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            conv_val, chart_val = xe_extract_both(soup, frm, to)
            chosen = None
            source = None
            if conv_val and conv_val > 0:
                chosen = conv_val; source = "xe:conversion"
            if chart_val and chart_val > 0:
                if not chosen:
                    chosen = chart_val; source = "xe:chart"
                else:
                    rel = abs(chart_val - conv_val) / max((chart_val + conv_val) / 2, Decimal("1e-9"))
                    if rel <= Decimal("0.03"):
                        chosen = (chart_val + conv_val) / Decimal(2); source = "xe:avg(chart,conv)"
                    # иначе оставляем conversion
            if not chosen:
                meta_val = xe_extract_meta(soup)
                if meta_val and meta_val > 0:
                    chosen = meta_val; source = "xe:meta"
            return chosen, url, {"source": source, "hydrated": hydrated}
        finally:
            try: page.close()
            except: pass
            try: context.close()
            except: pass
            try: browser.close()
            except: pass

def fetch_xe_via_requests(frm: str, to: str, amount: Decimal = Decimal(1)) -> Tuple[Optional[Decimal], str, Dict]:
    url = f"https://www.xe.com/currencyconverter/convert/?Amount={amount}&From={frm}&To={to}"
    hdrs = {"User-Agent": XE_UA, "Accept-Language": "ru-RU,ru;q=0.9"}
    r = requests.get(url, headers=hdrs, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    conv_val, chart_val = xe_extract_both(soup, frm, to)
    chosen = conv_val or chart_val or xe_extract_meta(soup)
    return chosen, url, {"source": "xe:requests", "hydrated": False}

def fetch_xe_direct(frm: str, to: str) -> Dict:
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return {"pair": f"{frm}-{to}", "price": 1.0, "url": f"https://www.xe.com/currencyconverter/convert/?Amount=1&From={frm}&To={to}", "ts": int(time.time()), "source": "xe:identity"}
    amount = Decimal(1)
    price, url, meta = fetch_xe_via_browser(frm, to, amount)
    if not price:
        price, url, meta = fetch_xe_via_requests(frm, to, amount)
    if not price or price <= 0:
        raise RuntimeError("XE direct: не удалось получить курс")
    return {"pair": f"{frm}-{to}", "price": float(price), "url": url, "ts": int(time.time()), "source": meta.get("source") or "xe"}

def fetch_xe_universal(frm: str, to: str) -> Dict:
    A, F = frm.upper(), to.upper()
    try:
        return fetch_xe_direct(A, F)
    except Exception:
        pass
    # гибрид
    if A in XE_STABLES:
        from_usd = Decimal(1)
        src_left = "stable≈USD"
    else:
        from_usd = None; src_left = None
        try:
            d = fetch_xe_direct(A, "USD")
            from_usd = _d(d["price"]); src_left = "xe(A→USD)"
        except Exception:
            try:
                g = fetch_gf(A, "USD")
                from_usd = _d(g["price"]); src_left = "gf(A→USD)"
            except Exception:
                pass
    usd_to = None; src_right = None
    try:
        d2 = fetch_xe_direct("USD", F)
        usd_to = _d(d2["price"]); src_right = "xe(USD→F)"
    except Exception:
        try:
            d3 = fetch_xe_direct(F, "USD")
            v = _d(d3["price"])
            if v and v > 0:
                usd_to = Decimal(1) / v; src_right = "xe(inv F→USD)"
        except Exception:
            pass
    if not from_usd or from_usd <= 0 or not usd_to or usd_to <= 0:
        raise RuntimeError("XE hybrid: не удалось собрать кросс-курс")
    price = from_usd * usd_to
    return {"pair": f"{A}-{F}", "price": float(price), "url": f"https://www.xe.com/currencyconverter/convert/?Amount=1&From={A}&To={F}", "ts": int(time.time()), "source": f"hybrid:{src_left}×{src_right}"}

# ====================== Bybit payments (из TXT) =================
BYBIT_PAYMENTS_MAP: Dict[str, List[Dict[str,str]]] = {}
def _load_bybit_payments_from_txt():
    path_local = os.path.join(os.path.dirname(__file__), "bybit_payment_methods.txt")
    path_alt   = "/mnt/data/bybit_payment_methods.txt"
    path = path_local if os.path.exists(path_local) else (path_alt if os.path.exists(path_alt) else None)
    if not path:
        return
    current = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            head = re.match(r"^===\s*([A-Z]{3})\s*===", line)
            if head:
                current = head.group(1).upper()
                BYBIT_PAYMENTS_MAP[current] = []
                continue
            if not line.strip() or current is None:
                continue
            m = re.match(r"^\s*([0-9]+)\s+(.+?)\s*$", line)
            if m:
                BYBIT_PAYMENTS_MAP[current].append({"id": m.group(1), "name": m.group(2)})
_load_bybit_payments_from_txt()

# ====================== XE codes ===============================
XE_CODES: List[str] = []
def _load_xe_codes():
    global XE_CODES
    fname_local = os.path.join(os.path.dirname(__file__), "xe_rates.json")
    fname_alt   = "/mnt/data/xe_rates.json"
    path = fname_local if os.path.exists(fname_local) else (fname_alt if os.path.exists(fname_alt) else None)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                js = json.load(f)
                rates = js.get("rates", {})
                if isinstance(rates, dict):
                    XE_CODES = sorted({k.upper().strip() for k in rates.keys() if isinstance(k, str)})
        except Exception:
            XE_CODES = []
    if not XE_CODES:
        XE_CODES = sorted(list({
            "USD","EUR","UAH","RUB","KZT","BYN","KGS","TJS","GEL","TRY","PLN","GBP","CZK","RON","MDL","HUF","AED","CNY","JPY","KRW","INR",
            "XAU","XAG","XPT","XPD","XDR",
            "BTC","ETH","BNB","SOL","ADA","XRP","LTC","DOGE","DOT","LINK",
            "USDT","USDC","DAI","TUSD","EURC","USDP"
        }))
_load_xe_codes()

# ====================== API ================================
@app.route("/api/binance_rate")
def api_binance_rate():
    asset = request.args.get("asset", "USDT").upper()
    fiat = request.args.get("fiat", "UAH").upper()
    side = request.args.get("side", "SELL").upper()
    pay_csv = (request.args.get("paytypes") or "").strip()
    paytypes = [p for p in (pay_csv.split(",") if pay_csv else []) if p]
    amount = request.args.get("amount", "20000")
    merchant = request.args.get("merchant", "true").lower() == "true"
    try:
        d = fetch_binance(asset, fiat, side, paytypes, amount, rows=10, merchant=merchant)
        return jsonify({"ok": True, **d})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/api/binance/paytypes")
def api_binance_paytypes():
    asset    = (request.args.get("asset") or "USDT").upper()
    fiat     = (request.args.get("fiat") or "UAH").upper()
    side     = (request.args.get("side") or "SELL").upper()
    amount   = request.args.get("amount", "20000")
    merchant = request.args.get("merchant_binance", "true").lower() == "true"
    try:
        items = discover_binance_paytypes(asset, fiat, side, amount, merchant)
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "items": []}), 502

@app.route("/api/bybit_rate")
def api_bybit_rate():
    token = request.args.get("asset", "USDT").upper()
    fiat  = request.args.get("fiat", "UAH").upper()
    side  = request.args.get("side", "SELL").upper()
    amount= request.args.get("amount", "20000")
    verified = request.args.get("verified", "false").lower() == "true"
    pay_csv  = (request.args.get("payments") or "").strip()
    payments = [p for p in (pay_csv.split(",") if pay_csv else []) if p]
    try:
        d = fetch_bybit(token, fiat, side, payments, amount, rows=10, verified=verified)
        return jsonify({"ok": True, **d})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/api/bybit/payments")
def api_bybit_payments():
    fiat = (request.args.get("fiat") or "UAH").upper()
    items = BYBIT_PAYMENTS_MAP.get(fiat, [])
    items = sorted(items, key=lambda x: (x["name"].lower(), int(x["id"])))
    return jsonify({"ok": True, "fiat": fiat, "items": items})

@app.route("/api/xe")
def api_xe():
    frm = request.args.get("from", "USD").upper()
    to  = request.args.get("to",   "UAH").upper()
    try:
        data = fetch_xe_universal(frm, to)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/api/xe/codes")
def api_xe_codes():
    return jsonify({"ok": True, "codes": XE_CODES})

@app.route("/api/gf_rate")
def api_gf_rate():
    asset = request.args.get("asset", "USD").upper()
    fiat  = request.args.get("fiat", "UAH").upper()
    try:
        data = fetch_gf(asset, fiat)
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

@app.route("/api/rates")
def api_rates():
    asset  = request.args.get("asset", "USDT").upper()
    fiat   = request.args.get("fiat", "UAH").upper()
    side   = request.args.get("side", "SELL").upper()
    amount = request.args.get("amount", "20000")

    merchant_binance = (request.args.get("merchant_binance", "true").lower() == "true")
    paytypes_csv     = (request.args.get("paytypes_binance") or "").strip()
    paytypes_binance = [p for p in (paytypes_csv.split(",") if paytypes_csv else []) if p]

    verified_bybit = (request.args.get("verified_bybit", "false").lower() == "true")
    payments_csv   = (request.args.get("payments_bybit") or "").strip()
    bybit_payments = [p for p in (payments_csv.split(",") if payments_csv else []) if p]

    out = {"google": None, "binance": None, "bybit": None}
    errors = {}

    try:
        out["binance"] = fetch_binance(asset, fiat, side, paytypes_binance, amount, rows=10, merchant=merchant_binance)
    except Exception as e:
        errors["binance"] = str(e)

    try:
        out["bybit"] = fetch_bybit(asset, fiat, side, bybit_payments, amount, rows=10, verified=verified_bybit)
    except Exception as e:
        errors["bybit"] = str(e)

    try:
        out["google"] = fetch_gf(asset, fiat)
    except Exception as e:
        errors["google"] = str(e)

    return jsonify({
        "ok": True,
        "params": {
            "asset": asset, "fiat": fiat, "side": side, "amount": amount,
            "merchant_binance": merchant_binance, "paytypes_binance": paytypes_binance,
            "verified_bybit": verified_bybit, "payments_bybit": bybit_payments
        },
        "google": out["google"],
        "binance": out["binance"],
        "bybit": out["bybit"],
        "errors": errors or None,
        "timestamp": int(time.time())
    })

@app.route("/healthz")
def healthz():
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
