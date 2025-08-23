# p2p_dashboard.py
# Flask-дэшборд: Binance • Bybit • Google Finance • XE (универсальные пары, устойчивый парсинг больших чисел)

import os
import re
import json
import time
from decimal import Decimal, InvalidOperation, getcontext
from typing import Optional, Tuple, List, Dict

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, Response

# ---- Playwright (мягкий импорт; если нет — XE работает через requests-фоллбек)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    PLAYWRIGHT_OK = True
except Exception:
    PLAYWRIGHT_OK = False

# Точность Decimal для длинных значений (BTC→KZT и т.п.)
getcontext().prec = 28

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

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
NUMBER_RE = re.compile(r"(?:\d{1,3}(?:[,\u00A0\u202F ]\d{3})+|\d+)(?:[.,]\d+)?")

def _normalize_number_string(s: str) -> str:
    """Нормализует строку числа к стандартному виду для Decimal."""
    s = (s or "").strip()
    # убрать все «узкие/несущие» пробелы
    s = s.replace("\u00A0", " ").replace("\u202F", " ")
    s = re.sub(r"\s+", "", s)  # убрать любые пробелы

    # Если присутствуют и ',' и '.', выбираем крайний правый как десятичный,
    # остальные удаляем как разделители тысяч
    if "," in s and "." in s:
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_dot > last_comma:
            # десятичный — точка, запятые убираем
            s = s.replace(",", "")
        else:
            # десятичный — запятая, точки убираем
            s = s.replace(".", "")
            s = s.replace(",", ".")
    else:
        # Только один из символов . или ,
        if "," in s:
            if s.count(",") > 1:
                # несколько запятых — это тысячные группы
                s = s.replace(",", "")
            else:
                # одна запятая: если после неё ровно 3 цифры — вероятно тысячная группа
                idx = s.rfind(",")
                decimals_len = len(s) - idx - 1
                if decimals_len == 3:
                    s = s.replace(",", "")
                else:
                    s = s.replace(",", ".")
        # только точки
        elif "." in s:
            if s.count(".") > 1:
                s = s.replace(".", "")
            else:
                idx = s.rfind(".")
                decimals_len = len(s) - idx - 1
                if decimals_len == 3:
                    s = s.replace(".", "")
                # иначе оставляем точку как десятичную

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

# ====================== Страница (две сетки) ====================
PAGE = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<title>P2P Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: dark light; --accent:#22c55e; --card:#12151c; --border:#242a36; --bg:#0b0d12; --fg:#e6e9ef; --muted:#9aa4b2; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:0; padding:24px; background:var(--bg); color:var(--fg); }
  .wrap { max-width: 1200px; margin: 0 auto; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:16px; padding:16px; position:relative; }
  .card::after{ content:""; position:absolute; left:0; top:0; width:100%; height:2px; background:linear-gradient(90deg, transparent, var(--accent), transparent); opacity:.35; border-radius:16px 16px 0 0; }
  h1 { margin:0 0 16px; font-size: 22px; font-weight:700; }
  h2 { margin:0 0 8px; }
  .muted { color:var(--muted); font-size: 12px; }
  .row { display:flex; gap:12px; flex-wrap: wrap; margin: 14px 0; }
  .row > * { flex: 1 1 180px; }
  label { display:block; font-size:12px; color:var(--muted); margin-bottom:6px; }
  input, select, button { font: inherit; }
  input, select { width:100%; padding:10px 12px; border-radius:10px; border:1px solid var(--border); background:#0f1218; color:var(--fg); }
  button { padding:10px 14px; border-radius:10px; border:1px solid var(--border); background:#1a2130; color:var(--fg); cursor:pointer; }
  button:hover { background:#20283a; border-color:#2d3546; }
  .btn-small { padding:6px 10px; font-size:12px; }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-top: 16px; }
  .rate { font-size: 34px; font-weight:700; margin: 6px 0 8px; }
  table { width:100%; border-collapse: collapse; margin-top: 10px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #222a38; font-size: 14px; }
  th { color:var(--muted); font-weight:600; font-size:12px; }
  .error { background:#311319; color:#ffb3c0; padding:10px 12px; border:1px solid #51212b; border-radius:10px; margin-top: 8px; }
  .ok { background:#122217; color:#b8ffcf; padding:6px 10px; border:1px solid #1e3a2b; border-radius:10px; display:inline-block; margin-top: 8px; }
  @media (max-width: 900px){ .grid { grid-template-columns: 1fr; } }
  .footer{ position:fixed; right:20px; bottom:15px; display:flex; align-items:center; gap:8px; font-size:12px; color:var(--muted); opacity:.85; }
  .footer img{ width:28px; height:28px; object-fit:contain; }
  .loader{ position:absolute; inset:0; display:none; align-items:center; justify-content:center; background:rgba(0,0,0,.35); border-radius:16px; }

  .mdrop { position: relative; display:inline-block; width:100%; }
  .mdrop-btn { width:100%; text-align:left; display:flex; align-items:center; justify-content:space-between; gap:8px; }
  .mdrop-btn .count { color:var(--muted); font-size:12px; }
  .mdrop-menu {
    position:absolute; z-index:20; margin-top:6px; min-width:320px; max-width:520px; max-height:420px;
    background:#0f1218; border:1px solid var(--border); border-radius:12px; box-shadow:0 20px 40px rgba(0,0,0,.45);
    display:none; overflow:hidden; flex-direction:column;
  }
  .mdrop.open .mdrop-menu { display:flex; }
  .mdrop-head { position: sticky; top: 0; background:#0f1218; border-bottom:1px solid var(--border); padding:8px; }
  .mdrop-body { padding:10px; overflow:auto; }
  .mdrop-grid { display:grid; grid-template-columns: 1fr 1fr; gap:8px 10px; align-items:stretch; }
  .mdrop-pill {
    min-height:32px; padding:4px 8px; border-radius:10px; border:1px solid var(--border); background:#0f1218;
    display:flex; align-items:center; cursor:pointer; user-select:none; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:12px;
  }
  .mdrop-pill:hover { background:#121a24; border-color:#2c3a4f; }
  .mdrop-pill.active { background:#0d1f16; border-color: rgba(34,197,94,.65); box-shadow: inset 0 0 0 1px rgba(34,197,94,.35); }
</style>
</head>
<body>
<div class="wrap">
  <h1>P2P Dashboard <span class="muted" id="ts"></span></h1>

  <!-- Глобальные фильтры -->
  <div class="card">
    <form id="filters" class="row" onsubmit="apply(event)">
      <div>
        <label>Актив</label>
        <select id="asset">
          <option>USDT</option><option>BTC</option><option>ETH</option>
          <option>BNB</option><option>SOL</option><option>USDC</option>
        </select>
      </div>
      <div>
        <label>Фиат</label>
        <select id="fiat">
          <option>UAH</option><option>USD</option><option>EUR</option>
          <option>RUB</option><option>KZT</option><option>TRY</option>
        </select>
      </div>
      <div>
        <label>Тип сделки</label>
        <select id="side">
          <option value="SELL" selected>SELL (вы продаёте актив)</option>
          <option value="BUY">BUY (вы покупаете актив)</option>
        </select>
      </div>
      <div>
        <label>Сумма (фиат)</label>
        <input id="amount" type="number" step="1" value="20000" />
      </div>
      <div style="align-self:end">
        <button type="submit">Применить</button>
        <button type="button" onclick="refreshNow()">Обновить</button>
      </div>
    </form>
  </div>

  <!-- Ряд 1: Binance • Bybit -->
  <div class="grid">
    <!-- Binance -->
    <div class="card" id="binance_card">
      <div class="loader" id="binance_loader">Загрузка...</div>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
        <h2 style="margin:0;">Binance</h2>
        <button class="btn-small" type="button" onclick="toggleFilters('binance_filters', this)">Фильтры</button>
      </div>
      <div id="binance_status" class="ok" style="display:none">OK</div>
      <div id="binance_error" class="error" style="display:none"></div>
      <div class="rate" id="binance_avg">—</div>
      <div class="muted" id="binance_prices">—</div>

      <div class="row" id="binance_filters" style="display:none; border-top:1px dashed var(--border); padding-top:12px;">
        <div>
          <label>Верифицированные продавцы</label>
          <select id="merchant_binance">
            <option value="true">Да</option>
            <option value="false">Нет</option>
          </select>
        </div>
        <div>
          <label>Платёжный метод</label>
          <div class="mdrop" id="dd_binance" onclick="event.stopPropagation()">
            <button type="button" class="mdrop-btn" onclick="mdropToggle('dd_binance'); event.stopPropagation();">
              <span>Выбрать методы</span> <span class="count" id="dd_binance_count">0</span>
            </button>
            <div class="mdrop-menu">
              <div class="mdrop-head">
                <input id="dd_binance_search" placeholder="Поиск метода..." oninput="onSearchInput('dd_binance')" />
              </div>
              <div class="mdrop-body">
                <div class="mdrop-grid" id="dd_binance_grid"></div>
              </div>
              <div class="mdrop-foot">
                <button type="button" class="js-confirm">Подтвердить</button>
                <button type="button" class="js-reset">Сбросить</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <table>
        <thead><tr><th>#</th><th>Трейдер</th><th>Цена</th><th>Объём</th><th>Мин</th><th>Макс</th></tr></thead>
        <tbody id="binance_tbody"></tbody>
      </table>
    </div>

    <!-- Bybit -->
    <div class="card" id="bybit_card">
      <div class="loader" id="bybit_loader">Загрузка...</div>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
        <h2 style="margin:0;">Bybit</h2>
        <button class="btn-small" type="button" onclick="toggleFilters('bybit_filters', this)">Фильтры</button>
      </div>
      <div id="bybit_status" class="ok" style="display:none">OK</div>
      <div id="bybit_error" class="error" style="display:none"></div>
      <div class="rate" id="bybit_avg">—</div>
      <div class="muted" id="bybit_prices">—</div>

      <div class="row" id="bybit_filters" style="display:none; border-top:1px dashed var(--border); padding-top:12px;">
        <div>
          <label>Верифицированные продавцы</label>
          <select id="verified_bybit">
            <option value="true">Да</option>
            <option value="false" selected>Нет</option>
          </select>
        </div>
        <div>
          <label>Платёжные методы</label>
          <div class="mdrop" id="dd_bybit" onclick="event.stopPropagation()">
            <button type="button" class="mdrop-btn" onclick="mdropToggle('dd_bybit'); event.stopPropagation();">
              <span>Выбрать методы</span> <span class="count" id="dd_bybit_count">0</span>
            </button>
            <div class="mdrop-menu">
              <div class="mdrop-head">
                <input id="dd_bybit_search" placeholder="Поиск метода..." oninput="onSearchInput('dd_bybit')" />
              </div>
              <div class="mdrop-body">
                <div class="mdrop-grid" id="dd_bybit_grid"></div>
              </div>
              <div class="mdrop-foot">
                <button type="button" class="js-confirm">Подтвердить</button>
                <button type="button" class="js-reset">Сбросить</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <table>
        <thead><tr><th>#</th><th>Трейдер</th><th>Цена</th><th>Объём</th><th>Мин</th><th>Макс</th></tr></thead>
        <tbody id="bybit_tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Ряд 2: XE • Google Finance -->
  <div class="grid">
    <!-- XE -->
    <div class="card" id="xe_card">
        <div class="loader" id="xe_loader">Загрузка...</div>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
        <h2 style="margin:0;">XE.com <span id="xe_pair" class="muted"></span></h2>
        <button class="btn-small" type="button" onclick="toggleFilters('xe_filters', this)">Фильтры</button>
      </div>
      <div class="row" id="xe_filters" style="display:none; border-top:1px dashed var(--border); padding-top:12px;">
        <div>
          <label>XE From</label>
          <input id="xe_from" list="xe_codes" placeholder="например, USD" />
        </div>
        <div>
          <label>XE To</label>
          <input id="xe_to" list="xe_codes" placeholder="например, UAH" />
        </div>
        <div style="align-self:end">
          <button class="btn-small" type="button" onclick="applyXE()">Применить XE</button>
          <button class="btn-small" type="button" onclick="refreshXENow()">Обновить XE</button>
        </div>
      </div>
      <datalist id="xe_codes"></datalist>

      <div id="xe_error" class="error" style="display:none"></div>
      <div class="rate" id="xe_price">—</div>
      <div class="muted">
        <span id="xe_ts">—</span>
        &nbsp;·&nbsp;<span id="xe_src" class="muted">—</span>
        &nbsp;·&nbsp;<a id="xe_link" href="#" target="_blank" rel="noopener" style="color:var(--muted)">Открыть XE</a>
      </div>
      <div style="margin-top:8px;">
        <span class="muted">Спред к Binance: <span id="xe_spread_bin">—</span></span>
        &nbsp;&nbsp;<span class="muted">Спред к Bybit: <span id="xe_spread_byb">—</span></span>
      </div>
    </div>

    <!-- Google Finance -->
    <div class="card" id="gf_card">
      <div class="loader" id="gf_loader">Загрузка...</div>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
        <h2 style="margin:0;">Google Finance <span id="gf_pair" class="muted"></span></h2>
        <button class="btn-small" type="button" onclick="toggleFilters('gf_filters', this)">Фильтры</button>
      </div>
      <div class="row" id="gf_filters" style="display:none; border-top:1px dashed var(--border); padding-top:12px;">
        <div>
          <label>GF From</label>
          <input id="gf_from" list="gf_codes" placeholder="например, USD" />
        </div>
        <div>
          <label>GF To</label>
          <input id="gf_to" list="gf_codes" placeholder="например, EUR" />
        </div>
        <div style="align-self:end">
          <button class="btn-small" type="button" onclick="applyGF()">Применить GF</button>
          <button class="btn-small" type="button" onclick="refreshGFNow()">Обновить GF</button>
        </div>
      </div>
      <datalist id="gf_codes"></datalist>
      <div id="gf_error" class="error" style="display:none"></div>
      <div class="rate" id="gf_price">—</div>
      <div class="muted">
        <span id="gf_ts">—</span>
        &nbsp;·&nbsp;<a id="gf_link" href="#" target="_blank" rel="noopener" style="color:var(--muted)">Открыть котировку</a>
      </div>
      <div style="margin-top:8px;">
        <span class="muted">Спред к Binance: <span id="gf_spread_bin">—</span></span>
        &nbsp;&nbsp;<span class="muted">Спред к Bybit: <span id="gf_spread_byb">—</span></span>
      </div>
    </div>
  </div>
</div>

<script>
  let timer = null; const REFRESH_MS = 30000;
  let xeTimer = null; const XE_REFRESH_MS = 30000;
  let gfTimer = null; const GF_REFRESH_MS = 30000;

  let lastBinanceAvg = null;
  let lastBybitAvg   = null;
  let lastGfPrice    = null;
  window.__lastXePrice = null;

  let selectedBinance = new Set();
  let selectedBybit   = new Set();
  const tempSelected  = { dd_binance: new Set(), dd_bybit: new Set() };
  const searchState   = { dd_binance: "", dd_bybit: "" };
  let binanceItems = []; let bybitItems = [];

  function fmtSmart(n){
    const v = Number(n);
    if (!isFinite(v)) return '—';
    const opts = v >= 1_000_000 ? {minimumFractionDigits:0, maximumFractionDigits:2}
                                : {minimumFractionDigits:2, maximumFractionDigits:6};
    return v.toLocaleString('ru-RU', opts);
  }
  function fmt(n){ return Number(n).toLocaleString('ru-RU', {minimumFractionDigits:2, maximumFractionDigits:6}); }
  function fmtShort(n){ return Number(n).toLocaleString('ru-RU', {maximumFractionDigits:6}); }
  function showLoader(id){ const el = document.getElementById(id); if (el) el.style.display='flex'; }
  function hideLoader(id){ const el = document.getElementById(id); if (el) el.style.display='none'; }

  function updateSpreads(){
    if (lastGfPrice != null){
      const s1 = (lastBinanceAvg==null) ? null : ((lastBinanceAvg - lastGfPrice) / lastGfPrice * 100);
      const s2 = (lastBybitAvg==null)   ? null : ((lastBybitAvg - lastGfPrice) / lastGfPrice * 100);
      document.getElementById('gf_spread_bin').innerHTML = s1==null ? '—' : ((s1>0?'+':'') + s1.toFixed(2) + '%');
      document.getElementById('gf_spread_byb').innerHTML = s2==null ? '—' : ((s2>0?'+':'') + s2.toFixed(2) + '%');
    }
    if (window.__lastXePrice != null){
      const base = window.__lastXePrice;
      const s1 = (lastBinanceAvg==null) ? null : ((lastBinanceAvg - base) / base * 100);
      const s2 = (lastBybitAvg==null)   ? null : ((lastBybitAvg - base) / base * 100);
      document.getElementById('xe_spread_bin').innerHTML = s1==null ? '—' : ((s1>0?'+':'') + s1.toFixed(2) + '%');
      document.getElementById('xe_spread_byb').innerHTML = s2==null ? '—' : ((s2>0?'+':'') + s2.toFixed(2) + '%');
    }
  }

  function toggleFilters(id, btn){
    const el = document.getElementById(id);
    const hidden = window.getComputedStyle(el).display === 'none';
    el.style.display = hidden ? '' : 'none';
    if (btn) btn.textContent = hidden ? 'Скрыть фильтры' : 'Фильтры';
    if (hidden){
      if (id==='binance_filters') loadBinancePaytypes();
      if (id==='bybit_filters')   loadBybitPayments();
    } else {
      closeAllDropdowns();
    }
  }

  function mdropToggle(ddId){
    const dd = document.getElementById(ddId);
    if (dd.classList.contains('open')){
      closeAndClear(ddId);
      return;
    }
    closeAllDropdowns();
    dd.classList.add('open');
    tempSelected[ddId] = new Set([...(ddId==='dd_binance'?selectedBinance:selectedBybit)]);
    renderDropdownOptions(ddId);
    const input = document.getElementById(ddId + '_search');
    if (input) { input.value = searchState[ddId] || ""; input.focus(); }
  }
  function closeAndClear(ddId){
    const dd = document.getElementById(ddId);
    if (!dd) return;
    dd.classList.remove('open');
    searchState[ddId] = "";
    const input = document.getElementById(ddId + '_search');
    if (input) input.value = "";
  }
  function closeAllDropdowns(){
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

  function onSearchInput(ddId){
    const input = document.getElementById(ddId + '_search');
    const val = (input?.value || '').toLowerCase().trim();
    searchState[ddId] = val;
    renderDropdownOptions(ddId);
  }
  function filteredItems(ddId){
    const list = (ddId==='dd_binance') ? binanceItems : bybitItems;
    const q = (searchState[ddId] || '').toLowerCase();
    if (!q) return list;
    return list.filter(it => (String(it.name||'') + ' ' + String(it.id||'')).toLowerCase().includes(q));
  }
  function renderDropdownOptions(ddId){
    const isBin = ddId==='dd_binance';
    const items = filteredItems(ddId);
    const temp  = tempSelected[ddId];
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
  function updateCounters(){
    document.getElementById('dd_binance_count').textContent = String(selectedBinance.size);
    document.getElementById('dd_bybit_count').textContent   = String(selectedBybit.size);
  }
  function wireDropdown(ddId){
    const root = document.getElementById(ddId);
    if (!root) return;
    const menu = root.querySelector('.mdrop-menu');
    if (!menu || menu.__wired) return;
    menu.addEventListener('click', (e) => {
      e.stopPropagation();
      if (e.target.closest('.js-confirm')){
        if (ddId==='dd_binance') selectedBinance = new Set([...tempSelected[ddId]]);
        if (ddId==='dd_bybit')   selectedBybit   = new Set([...tempSelected[ddId]]);
        updateCounters();
        refreshNow();
        closeAllDropdowns();
        return;
      }
      if (e.target.closest('.js-reset')){
        tempSelected[ddId] = new Set();
        renderDropdownOptions(ddId);
        const cntSpan = document.getElementById(ddId === 'dd_binance' ? 'dd_binance_count' : 'dd_bybit_count');
        if (cntSpan) cntSpan.textContent = '0';
        return;
      }
    });
    menu.__wired = true;
  }

  async function loadBinancePaytypes(){
    const asset = document.getElementById('asset').value;
    const fiat  = document.getElementById('fiat').value;
    const side  = document.getElementById('side').value;
    const amount= document.getElementById('amount').value;
    const merch = document.getElementById('merchant_binance')?.value ?? 'true';
    const url = '/api/binance/paytypes?' + new URLSearchParams({asset,fiat,side,amount,merchant_binance:merch});
    try{
      const r = await fetch(url);
      const js = await r.json();
      binanceItems = js.items || [];
      [...selectedBinance].forEach(id => { if (!binanceItems.find(it => String(it.id)===id)) selectedBinance.delete(id); });
      updateCounters();
      return binanceItems;
    }catch(e){
      binanceItems = []; selectedBinance.clear(); updateCounters();
      return [];
    }
  }
  async function loadBybitPayments(){
    const fiat = document.getElementById('fiat').value;
    try{
      const r = await fetch('/api/bybit/payments?fiat=' + encodeURIComponent(fiat));
      const js = await r.json();
      bybitItems = js.items || [];
      [...selectedBybit].forEach(id => { if (!bybitItems.find(it => String(it.id)===id)) selectedBybit.delete(id); });
      updateCounters();
      return bybitItems;
    }catch(e){
      bybitItems = []; selectedBybit.clear(); updateCounters();
      return [];
    }
  }

  function paramsFromUI(){
    return {
      asset:   document.getElementById('asset').value,
      fiat:    document.getElementById('fiat').value,
      side:    document.getElementById('side').value,
      amount:  document.getElementById('amount').value,
      merchant_binance: document.getElementById('merchant_binance')?.value ?? 'true',
      paytypes_binance: [...selectedBinance].join(','),
      verified_bybit: document.getElementById('verified_bybit')?.value ?? 'false',
      payments_bybit:  [...selectedBybit].join(',')
    };
  }

  async function loadBinance(){
    const p = paramsFromUI();
    const url = '/api/binance_rate?' + new URLSearchParams({asset:p.asset, fiat:p.fiat, side:p.side, amount:p.amount, paytypes:p.paytypes_binance, merchant:p.merchant_binance}).toString();
    showLoader('binance_loader');
    try{
      const res = await fetch(url);
      const data = await res.json();
      const bErr = document.getElementById('binance_error');
      const bOk  = document.getElementById('binance_status');
      if (!data.ok){
        bErr.style.display = ''; bErr.textContent = 'Ошибка: ' + (data.error || 'unknown');
        bOk.style.display = 'none';
        document.getElementById('binance_avg').textContent = '—';
        document.getElementById('binance_prices').textContent = '—';
        document.getElementById('binance_tbody').innerHTML = '';
        lastBinanceAvg = null;
      } else {
        bErr.style.display = 'none'; bOk.style.display = '';
        document.getElementById('binance_avg').textContent = (data.avg!=null? fmt(data.avg):'—') + ' ' + p.fiat;
        document.getElementById('binance_prices').textContent = data.prices && data.prices.length ? ('#3–5: ' + data.prices.slice(2,5).map(fmt).join(' • ')) : '—';
        const tb = document.getElementById('binance_tbody'); tb.innerHTML = '';
        (data.items||[]).forEach((it, i) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${i+1}</td><td>${it.name||'-'}</td><td>${fmt(it.price)}</td><td>${it.volume??'-'}</td><td>${it.min??'-'}</td><td>${it.max??'-'}</td>`;
          tb.appendChild(tr);
        });
        lastBinanceAvg = data.avg ?? null;
      }
    }catch(e){
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

    async function loadBybit(){
    const p = paramsFromUI();
    const url = '/api/bybit_rate?' + new URLSearchParams({asset:p.asset, fiat:p.fiat, side:p.side, amount:p.amount, payments:p.payments_bybit, verified:p.verified_bybit}).toString();
    showLoader('bybit_loader');
    try{
      const res = await fetch(url);
      const data = await res.json();
      const yErr = document.getElementById('bybit_error');
      const yOk  = document.getElementById('bybit_status');
      if (!data.ok){
        yErr.style.display = ''; yErr.textContent = 'Ошибка: ' + (data.error || 'unknown');
        yOk.style.display = 'none';
        document.getElementById('bybit_avg').textContent = '—';
        document.getElementById('bybit_prices').textContent = '—';
        document.getElementById('bybit_tbody').innerHTML = '';
        lastBybitAvg = null;
      } else {
        yErr.style.display = 'none'; yOk.style.display = '';
        document.getElementById('bybit_avg').textContent = (data.avg!=null? fmt(data.avg):'—') + ' ' + p.fiat;
        document.getElementById('bybit_prices').textContent = data.prices && data.prices.length ? ('#3–5: ' + data.prices.slice(2,5).map(fmt).join(' • ')) : '—';
        const tb = document.getElementById('bybit_tbody'); tb.innerHTML = '';
        (data.items||[]).forEach((it, i) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${i+1}</td><td>${it.name||'-'}</td><td>${fmt(it.price)}</td><td>${it.volume??'-'}</td><td>${it.min??'-'}</td><td>${it.max??'-'}</td>`;
          tb.appendChild(tr);
        });
        lastBybitAvg = data.avg ?? null;
      }
    }catch(e){
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

  async function fillXeCodes(){
    try{
      const r = await fetch('/api/xe/codes');
      const js = await r.json();
      const list = (js.codes||[]).sort();
      const dl = document.getElementById('xe_codes');
      const dl2 = document.getElementById('gf_codes');
      dl.innerHTML = ''; dl2.innerHTML = '';
      list.forEach(code => {
        const opt1 = document.createElement('option'); opt1.value = code; dl.appendChild(opt1);
        const opt2 = document.createElement('option'); opt2.value = code; dl2.appendChild(opt2);
      });
      if (!document.getElementById('xe_from').value) document.getElementById('xe_from').value = 'USD';
      if (!document.getElementById('xe_to').value)   document.getElementById('xe_to').value   = document.getElementById('fiat').value || 'UAH';
      if (!document.getElementById('gf_from').value) document.getElementById('gf_from').value = 'USD';
      if (!document.getElementById('gf_to').value)   document.getElementById('gf_to').value   = document.getElementById('fiat').value || 'UAH';
    }catch(e){}
  }
  function currentXePair(){
    const f = (document.getElementById('xe_from').value||'').toUpperCase().trim();
    const t = (document.getElementById('xe_to').value||'').toUpperCase().trim();
    if (!f || !t) return null; return {from:f, to:t};
  }
  function applyXE(){
    refreshXENow();
    const pr = currentXePair();
    if (pr) history.replaceState(null, '', '?' + new URLSearchParams({...Object.fromEntries(new URLSearchParams(location.search)), xe_from:pr.from, xe_to:pr.to}).toString());
  }
  async function loadXE(){
    const pr = currentXePair();
    const err = document.getElementById('xe_error');
    if (!pr){
      err.style.display = ''; err.textContent = 'Укажите пары XE (From/To).';
      return;
    }
    const url = '/api/xe?' + new URLSearchParams({from: pr.from, to: pr.to}).toString();
    showLoader('xe_loader');
    try{
      const r = await fetch(url);
      const js = await r.json();
      document.getElementById('xe_pair').textContent = `${pr.from}-${pr.to}`;
      if (!js.ok){
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
        document.getElementById('xe_ts').textContent = 'TS: ' + new Date(d.ts*1000).toLocaleTimeString('ru-RU');
        document.getElementById('xe_src').textContent = d.source || 'xe';
        document.getElementById('xe_link').href = d.url || '#';
        window.__lastXePrice = d.price;
      }
    }catch(e){
      err.style.display = ''; err.textContent = 'Ошибка сети/парсинга XE';
       document.getElementById('xe_spread_bin').textContent = '—';
      document.getElementById('xe_spread_byb').textContent = '—';
      window.__lastXePrice = null;
      } finally {
      hideLoader('xe_loader');
      updateSpreads();

    }
  }

  function currentGfPair(){
    const f = (document.getElementById('gf_from').value||'').toUpperCase().trim();
    const t = (document.getElementById('gf_to').value||'').toUpperCase().trim();
    if (!f || !t) return null; return {from:f, to:t};
  }
  function applyGF(){
    refreshGFNow();
    const pr = currentGfPair();
    if (pr) history.replaceState(null, '', '?' + new URLSearchParams({...Object.fromEntries(new URLSearchParams(location.search)), gf_from:pr.from, gf_to:pr.to}).toString());
  }
  async function loadGF(){
    const pr = currentGfPair();
    const gErr = document.getElementById('gf_error');
    if (!pr){
      gErr.style.display = ''; gErr.textContent = 'Укажите пары GF (From/To).';
      return;
    }
    document.getElementById('gf_pair').textContent = `${pr.from}-${pr.to}`;
    const url = '/api/gf_rate?' + new URLSearchParams({asset: pr.from, fiat: pr.to}).toString();
    showLoader('gf_loader');
    try{
      const r = await fetch(url);
      const js = await r.json();
      if (!js.ok){
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
        document.getElementById('gf_ts').textContent = 'TS: ' + new Date(js.ts*1000).toLocaleTimeString('ru-RU');
        document.getElementById('gf_link').href = js.url || '#';
        lastGfPrice = js.price;
      }
    }catch(e){
      gErr.style.display = ''; gErr.textContent = 'Ошибка сети/парсинга GF';
      document.getElementById('gf_spread_bin').textContent = '—';
      document.getElementById('gf_spread_byb').textContent = '—';
      lastGfPrice = null;
    } finally {
      hideLoader('gf_loader');
      updateSpreads();
    }
  }
  function refreshGFNow(){ loadGF(); if (gfTimer) clearInterval(gfTimer); gfTimer = setInterval(loadGF, GF_REFRESH_MS); }

  function refreshNow(){
    loadBinance();
    loadBybit();
    document.getElementById('ts').textContent = '• обновлено: ' + new Date().toLocaleTimeString('ru-RU');
    if (timer) clearInterval(timer);
    timer = setInterval(() => { loadBinance(); loadBybit(); document.getElementById('ts').textContent = '• обновлено: ' + new Date().toLocaleTimeString('ru-RU'); }, REFRESH_MS);
  }
  function refreshXENow(){ loadXE(); if (xeTimer) clearInterval(xeTimer); xeTimer = setInterval(loadXE, XE_REFRESH_MS); }
  function apply(ev){ ev.preventDefault(); refreshNow(); refreshXENow(); refreshGFNow(); }

  window.addEventListener('DOMContentLoaded', async () => {
    await fillXeCodes();

    const q = new URLSearchParams(location.search);
    const xf = q.get('xe_from'); const xt = q.get('xe_to');
    const gfF = q.get('gf_from'); const gfT = q.get('gf_to');
    if (xf) document.getElementById('xe_from').value = xf;
    if (xt) document.getElementById('xe_to').value   = xt;
    if (gfF) document.getElementById('gf_from').value = gfF;
    if (gfT) document.getElementById('gf_to').value   = gfT;

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
</script>

<footer class="footer">
  <span>Powered by bergamot1144</span>
  <img src="https://cdn0.iconfinder.com/data/icons/fruits-139/185/Bergamot-512.png" alt="logo">
</footer>
</body>
</html>
"""

@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html; charset=utf-8")

@app.route("/api/xe/codes")
def xe_codes_api():
    return jsonify({"ok": True, "codes": XE_CODES})

@app.route("/healthz")
def healthz():
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
