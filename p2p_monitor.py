# p2p_dashboard.py
# Обновлено:
# - Мягкая обработка ошибок/пустых данных для Binance/Bybit
# - XE и Google Finance — в одном ряду, как Binance/Bybit
# - Фильтры XE: From/To (single-select с поиском) по списку валют из JSON
# - Автообновление: рынки 30с, XE 15с
# - use_reloader=False (Playwright)

import os
import re
import time
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, Response

# === Playwright для XE ===
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# ------------------ Куки / заголовки для P2P ------------------
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

# ------------------ Утилиты общие ------------------
def _avg_3_5(prices):
    return round(sum(prices[2:5]) / 3.0, 6) if len(prices) >= 5 else None

def _fmt_float(x):
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).replace("\u00A0", "").replace(" ", "").replace(",", "."))
        except Exception:
            return None

# ------------------ Binance ------------------
def fetch_binance(asset="USDT", fiat="UAH", side="SELL", pay_types=None, amount="20000", rows=10, merchant=True, page=1):
    """
    Возвращает словарь: {items, prices, avg, error}
    items: top-5 карточек (имя, цена, мин, макс, объём)
    prices: массив цен top-5
    avg: среднее по 3–5 (или None, если данных мало)
    error: текст ошибки, если что-то не так (не бросаем исключение)
    """
    payload = {
        "asset": asset, "fiat": fiat, "merchantCheck": bool(merchant),
        "page": int(page), "payTypes": list(pay_types or []),
        "publisherType": None, "rows": int(rows),
        "tradeType": side, "transAmount": str(amount),
    }
    try:
        r = requests.post(BINANCE_URL, headers=BINANCE_HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        return {"items": [], "prices": [], "avg": None, "error": f"network/json: {e}"}

    if js.get("code") != "000000" or "data" not in js:
        return {"items": [], "prices": [], "avg": None, "error": f"api: {js}"}

    data = js["data"] or []
    items, prices = [], []
    for ad in data[:5]:
        adv = ad.get("adv", {}) or {}
        seller = (ad.get("advertiser") or {}).get("nickName") or "-"
        price  = _fmt_float(adv.get("price"))
        if price is None:
            continue
        items.append({
            "name": seller,
            "price": price,
            "min": adv.get("minSingleTransAmount"),
            "max": adv.get("maxSingleTransAmount"),
            "volume": adv.get("surplusAmount"),
        })
        prices.append(price)

    return {"items": items, "prices": prices, "avg": _avg_3_5(prices), "error": None}

def discover_binance_paytypes(asset="USDT", fiat="UAH", side="SELL", amount="20000", merchant=True, pages=3, rows=20):
    """
    Сканирует несколько страниц и возвращает уникальные payTypes: [{"id","name"},...]
    """
    seen = {}
    for p in range(1, pages+1):
        payload = {
            "asset": asset, "fiat": fiat, "merchantCheck": bool(merchant),
            "page": p, "payTypes": [], "publisherType": None,
            "rows": int(rows), "tradeType": side, "transAmount": str(amount),
        }
        try:
            r = requests.post(BINANCE_URL, headers=BINANCE_HEADERS, json=payload, timeout=15)
            if r.status_code != 200:
                break
            js = r.json()
        except Exception:
            break
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
                ident = (ident or "").strip()
                if ident and ident not in seen:
                    seen[ident] = ident
    items = [{"id": k, "name": v} for k, v in seen.items()]
    items.sort(key=lambda x: (x["name"].lower(), x["id"]))
    return items

# ------------------ Bybit ------------------
def fetch_bybit(token="USDT", fiat="UAH", side="SELL", payments=None, amount="20000", rows=10, verified=False):
    """
    Аналогично Binance: {items, prices, avg, error}
    """
    side_map = {"SELL": "0", "BUY": "1"}
    payload = {
        "tokenId": token, "currencyId": fiat, "payment": payments or [],
        "side": side_map.get(side.upper(), "1"),
        "size": str(rows), "page": "1",
        "amount": str(amount), "authMaker": bool(verified),
        "canTrade": False, "shieldMerchant": False, "reputation": False, "country": ""
    }
    try:
        r = requests.post(BYBIT_URL, headers=BYBIT_HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        return {"items": [], "prices": [], "avg": None, "error": f"network/json: {e}"}

    result = js.get("result", {}) if isinstance(js, dict) else {}
    data = (result.get("items", []) or [])[:5]

    items, prices = [], []
    for ad in data:
        name  = ad.get("nickName") or "-"
        price = _fmt_float(ad.get("price"))
        if price is None:
            continue
        items.append({
            "name": name,
            "price": price,
            "min": ad.get("minAmount"),
            "max": ad.get("maxAmount"),
            "volume": ad.get("lastQuantity"),
        })
        prices.append(price)
    return {"items": items, "prices": prices, "avg": _avg_3_5(prices), "error": None}

# ------------------ Google Finance ------------------
GF_HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}
_num_re = re.compile(r"[-+]?\d{1,3}(?:[ \u00A0]?\d{3})*(?:[.,]\d+)?")

def _num_to_float(s: str) -> float:
    m = _num_re.search(s or "")
    if not m:
        raise ValueError(f"no number in '{s}'")
    t = m.group(0).replace("\u00A0", " ").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    return float(t)

def _gf_price_direct(asset: str, fiat: str) -> tuple[float, str]:
    A, F = asset.upper(), fiat.upper()
    url  = f"https://www.google.com/finance/quote/{A}-{F}"
    r = requests.get(url, headers=GF_HEADERS, timeout=12)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    blk = soup.select_one(f'div[jscontroller="NdbN0c"][jsname="AS5Pxb"][data-source="{A}"][data-target="{F}"]')

    if blk and blk.has_attr("data-last-price"):
        return float(blk["data-last-price"]), url

    if blk:
        node = blk.select_one("div.YMlKec.fxKbKc") or blk.select_one("div.YMlKec")
        if node and node.text:
            return _num_to_float(node.get_text(" ", strip=True)), url

    m = re.findall(r'data-last-price="([^"]+)"', r.text)
    if m:
        return float(m[-1]), url

    node = soup.select_one("div.YMlKec.fxKbKc") or soup.select_one("div.YMlKec")
    if node and node.text:
        return _num_to_float(node.get_text(" ", strip=True)), url

    raise RuntimeError("GF: не удалось извлечь цену")

def _gf_only_price(asset: str, fiat: str) -> float:
    p, _ = _gf_price_direct(asset, fiat)
    return p

def fetch_gf(asset: str, fiat: str):
    A, F = asset.upper(), fiat.upper()
    direct_price, url = _gf_price_direct(A, F)

    cross = None
    try:
        if A != "USD" and F != "USD":
            a_usd = _gf_only_price(A, "USD")
            usd_f = _gf_only_price("USD", F)
            cross = a_usd * usd_f
    except Exception:
        cross = None

    def rng(a, f):
        if f == "UAH":
            return {
                "USDT": (5, 200), "USDC": (5, 200), "DAI": (5, 200), "TUSD": (5, 200), "USD": (5, 200),
                "BTC": (1e5, 1e8), "ETH": (5e3, 5e7), "BNB": (1e3, 2e6), "SOL": (200, 1e6),
            }.get(a, (1e-9, 1e12))
        return (1e-9, 1e12)

    lo, hi = rng(A, F)
    chosen = direct_price
    in_range = (lo <= chosen <= hi)

    if cross is not None:
        if not in_range:
            chosen = cross
        else:
            rel = abs(chosen - cross) / max(cross, 1e-12)
            if rel > 0.25:
                chosen = cross

    if A in {"USDT", "USDC", "DAI", "TUSD", "USD"} and F in {"UAH", "USD", "EUR"}:
        if not (0.01 < chosen < 1000) and cross is not None and (0.01 < cross < 1000):
            chosen = cross

    return {"pair": f"{A}-{F}", "price": float(chosen), "url": url, "ts": int(time.time())}

# ------------------ XE.com (Playwright) ------------------
XE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit(537.36) (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
NAV_TIMEOUT = 15000
SEL_TIMEOUT = 6000
RE_NUM = re.compile(r"[0-9]+(?:[ \u00A0]?[0-9]{3})*(?:[.,][0-9]+)?")

def to_float(num_str: str) -> float:
    s = (num_str or "").replace("\u00A0", " ").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    return float(s)

def xe_extract_both(soup: BeautifulSoup, frm: str, to: str) -> Tuple[Optional[float], Optional[float]]:
    frm_u, to_u = frm.upper(), to.upper()
    conv_val = None
    chart_val = None

    for box in soup.select("div[data-testid='conversion']"):
        header_p = None
        for p in box.find_all("p"):
            if p.get_text(" ", strip=True).endswith("="):
                header_p = p
                break
        if header_p is not None:
            value_p = header_p.find_next_sibling("p")
            if value_p is not None:
                txt = value_p.get_text("", strip=True)
                m = RE_NUM.search(txt)
                if m:
                    try:
                        conv_val = to_float(m.group(0))
                        break
                    except Exception:
                        pass

    for p in soup.select("section[data-testid='currency-conversion-chart-stats-table'] p"):
        txt = p.get_text(" ", strip=True)
        up  = txt.upper()
        if up.startswith(f"1 {frm_u}") and "=" in up and to_u in up:
            right = txt.split("=", 1)[1]
            m = RE_NUM.search(right)
            if m:
                try:
                    chart_val = to_float(m.group(0))
                except Exception:
                    chart_val = None
            break

    return conv_val, chart_val

def xe_extract_meta(soup: BeautifulSoup) -> Optional[float]:
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    if not meta:
        return None
    content = meta.get("content") or ""
    nums = RE_NUM.findall(content)
    if len(nums) >= 2:
        try:
            return to_float(nums[1])
        except Exception:
            return None
    return None

def fetch_xe_browser(frm: str, to: str, amount: float = 1.0) -> dict:
    A, F = frm.upper(), to.upper()
    url = f"https://www.xe.com/currencyconverter/convert/?Amount={amount}&From={A}&To={F}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            locale="ru-RU",
            user_agent=XE_UA,
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)

            waited_any = False
            for sel in [
                "div[data-testid='conversion'] p",
                "section[data-testid='currency-conversion-chart-stats-table'] p",
                "meta[property='og:description'], meta[name='description']",
            ]:
                try:
                    page.wait_for_selector(sel, timeout=SEL_TIMEOUT)
                    waited_any = True
                    break
                except PWTimeoutError:
                    continue

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            conv_val, chart_val = xe_extract_both(soup, A, F)

            chosen = None
            source = None

            if conv_val is not None and conv_val > 0:
                chosen = conv_val
                source = "conversion"

            if chart_val is not None and chart_val > 0:
                if chosen is None:
                    chosen = chart_val
                    source = "chart"
                else:
                    rel = abs(chart_val - conv_val) / max((chart_val + conv_val) / 2.0, 1e-9)
                    if rel <= 0.03:
                        chosen = (chart_val + conv_val) / 2.0
                        source = "avg(chart,conv)"
                    else:
                        chosen = conv_val
                        source = "conversion"

            if chosen is None:
                meta_val = xe_extract_meta(soup)
                if meta_val is not None and meta_val > 0:
                    chosen = meta_val
                    source = "meta"

            if chosen is None:
                raise RuntimeError("не найден валидный курс (chart=0/None, conversion=None, meta=None)")

            return {
                "pair": f"{A}-{F}",
                "price": float(chosen),
                "url": url,
                "ts": int(time.time()),
                "source": source,
                "hydrated": waited_any,
                "raw": {"conversion": conv_val, "chart": chart_val}
            }
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

# ------------------ Bybit payments из txt ------------------
BYBIT_PAYMENTS_MAP = {}
def _load_bybit_payments():
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

_load_bybit_payments()

# ------------------ XE symbols (из твоего JSON: список кодов) ------------------
XE_SYMBOLS = sorted([
    "ADA","AED","AFN","ALL","AMD","ANG","AOA","ARS","ATS","AUD","AWG","AZM","AZN","BAM","BBD","BCH",
    "BDT","BEF","BGN","BHD","BIF","BMD","BND","BOB","BRL","BSD","BTC","BTN","BWP","BYN","BYR","BZD",
    "CAD","CDF","CHF","CLF","CLP","CNH","CNY","COP","CRC","CUC","CUP","CVE","CYP","CZK","DEM","DJF",
    "DKK","DOGE","DOP","DOT","DZD","EEK","EGP","ERN","ESP","ETB","ETH","EUR","EURC","FIM","FJD","FKP",
    "FRF","GBP","GEL","GGP","GHC","GHS","GIP","GMD","GNF","GRD","GTQ","GYD","HKD","HNL","HRK","HTG",
    "HUF","IDR","IEP","ILS","IMP","INR","IQD","IRR","ISK","ITL","JEP","JMD","JOD","JPY","KES","KGS",
    "KHR","KMF","KPW","KRW","KWD","KYD","KZT","LAK","LBP","LINK","LKR","LRD","LSL","LTC","LTL","LUF",
    "LUNA","LVL","LYD","MAD","MDL","MGA","MGF","MKD","MMK","MNT","MOP","MRO","MRU","MTL","MUR","MVR",
    "MWK","MXN","MXV","MYR","MZM","MZN","NAD","NGN","NIO","NLG","NOK","NPR","NZD","OMR","PAB","PEN",
    "PGK","PHP","PKR","PLN","PTE","PYG","QAR","ROL","RON","RSD","RUB","RWF","SAR","SBD","SCR","SDD",
    "SDG","SEK","SGD","SHP","SIT","SKK","SLE","SLL","SOL","SOS","SPL","SRD","SRG","STD","STN","SVC",
    "SYP","SZL","THB","TJS","TMM","TMT","TND","TOP","TRL","TRY","TTD","TVD","TWD","TZS","UAH","UGX",
    "UNI","USD","USDC","USDP","UYU","UZS","VAL","VEB","VED","VEF","VES","VND","VUV","WST","XAF","XAG",
    "XAU","XBT","XCD","XCG","XDR","XLM","XOF","XPD","XPF","XPT","XRP","YER","ZAR","ZMK","ZMW","ZWD",
    "ZWG","ZWL"
])

@app.route("/api/xe/symbols")
def api_xe_symbols():
    return jsonify({"ok": True, "symbols": XE_SYMBOLS})

# ------------------ API: справочники ------------------
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

@app.route("/api/bybit/payments")
def api_bybit_payments():
    fiat = (request.args.get("fiat") or "UAH").upper()
    items = BYBIT_PAYMENTS_MAP.get(fiat, [])
    items = sorted(items, key=lambda x: (x["name"].lower(), int(x["id"])))
    return jsonify({"fiat": fiat, "count": len(items), "items": items})

# ------------------ Единый API по рынкам ------------------
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

    errors = {}

    gf = None
    try:
        gf = fetch_gf(asset, fiat)
    except Exception as e:
        errors["google"] = str(e)

    bn = fetch_binance(asset, fiat, side, paytypes_binance, amount, rows=10, merchant=merchant_binance)
    if bn.get("error"):
        errors["binance"] = bn["error"]

    by = fetch_bybit(asset, fiat, side, bybit_payments, amount, rows=10, verified=verified_bybit)
    if by.get("error"):
        errors["bybit"] = by["error"]

    return jsonify({
        "ok": True,
        "params": {
            "asset": asset, "fiat": fiat, "side": side, "amount": amount,
            "merchant_binance": merchant_binance, "paytypes_binance": paytypes_binance,
            "verified_bybit": verified_bybit, "payments_bybit": bybit_payments
        },
        "google": gf,
        "binance": {k: v for k, v in bn.items() if k in ("items","prices","avg")},
        "bybit":   {k: v for k, v in by.items() if k in ("items","prices","avg")},
        "errors": errors or None,
        "timestamp": int(time.time())
    })

# ------------------ API XE: отдельные эндпоинты ------------------
@app.route("/api/xe")
def api_xe():
    frm = request.args.get("from", "USD").upper()
    to  = request.args.get("to",   "UAH").upper()
    try:
        amount = float(request.args.get("amount", "1") or "1")
    except Exception:
        amount = 1.0

    try:
        data = fetch_xe_browser(frm, to, amount)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": f"XE browser error: {e}"}), 502

@app.route("/api/xe/debug")
def api_xe_debug():
    frm = request.args.get("from", "USD").upper()
    to  = request.args.get("to",   "UAH").upper()
    amount = request.args.get("amount", "1")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                locale="ru-RU",
                user_agent=XE_UA,
                viewport={"width": 1280, "height": 900},
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
            )
            page = context.new_page()
            page.goto(f"https://www.xe.com/currencyconverter/convert/?Amount={amount}&From={frm}&To={to}",
                      wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            try:
                page.wait_for_selector("div[data-testid='conversion'] p, section[data-testid='currency-conversion-chart-stats-table'] p",
                                       timeout=SEL_TIMEOUT)
            except Exception:
                pass
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            conv_val, chart_val = xe_extract_both(soup, frm, to)
            meta_val = xe_extract_meta(soup)
            return jsonify({"ok": True, "raw": {"conversion": conv_val, "chart": chart_val, "meta": meta_val}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502

# ------------------ Страница ------------------
PAGE = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<title>P2P Dashboard: Binance • Bybit • Google Finance • XE</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root {
    color-scheme: dark light;
    --accent: #22c55e;
    --card: #12151c;
    --border: #242a36;
    --bg: #0b0d12;
    --fg: #e6e9ef;
    --muted: #9aa4b2;
  }
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
  button:hover { background:#20283a; border-color: #2d3546; }
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
  .chip { background:#0e1622; border:1px solid #223047; color:var(--muted); padding:3px 8px; border-radius:999px; font-size:12px; }

  /* Dropdown (multi и single используют один стиль) */
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
  .mdrop-head input{
    width:100%; padding:8px 10px; border-radius:10px; border:1px solid var(--border); background:#0f1218; color:var(--fg);
    outline:none;
  }
  .mdrop-head input:focus{ border-color: var(--accent); box-shadow: 0 0 0 2px rgba(34,197,94,.15); }

  .mdrop-body { padding:10px; overflow:auto; }
  .mdrop-grid { display:grid; grid-template-columns: 1fr 1fr; gap:8px 10px; align-items:stretch; }
  .mdrop-pill {
    min-height:32px; padding:4px 8px; border-radius:10px; border:1px solid var(--border); background:#0f1218;
    display:flex; align-items:center; justify-content:flex-start; text-align:left; cursor:pointer; user-select:none;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:12px;
  }
  .mdrop-pill:hover { background:#121a24; border-color:#2c3a4f; }
  .mdrop-pill.active { background:#0d1f16; border-color: rgba(34,197,94,.65); box-shadow: inset 0 0 0 1px rgba(34,197,94,.35); }

  .mdrop-foot {
    position: sticky; bottom: 0; background:#0f1218; border-top:1px solid var(--border); padding:8px;
    display:grid; grid-template-columns: 1fr 1fr; gap:8px;
  }
  .mdrop-foot button { width:100%; }
  .mdrop-foot button:first-child { border-color: #1e2b22; background:#112318; }
  .mdrop-foot button:first-child:hover { border-color:#244a33; background:#14301f; }
  .mdrop-foot button:last-child { border-color:#2a1f21; background:#231317; }
  .mdrop-foot button:last-child:hover { border-color:#3a2a2d; background:#2a171c; }
</style>
</head>
<body>
<div class="wrap">
  <h1>P2P Dashboard <span class="muted" id="ts"></span></h1>

  <!-- Глобальные фильтры + XE From/To -->
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

      <!-- XE From/To (single-select + поиск) -->
      <div>
        <label>XE From</label>
        <div class="mdrop" id="xe_from" onclick="event.stopPropagation()">
          <button type="button" class="mdrop-btn" onclick="sdToggle('xe_from'); event.stopPropagation();">
            <span id="xe_from_label">USD</span>
          </button>
          <div class="mdrop-menu">
            <div class="mdrop-head">
              <input id="xe_from_search" placeholder="Поиск валюты..." oninput="onSdSearch('xe_from')" />
            </div>
            <div class="mdrop-body">
              <div class="mdrop-grid" id="xe_from_grid"></div>
            </div>
          </div>
        </div>
      </div>
      <div>
        <label>XE To</label>
        <div class="mdrop" id="xe_to" onclick="event.stopPropagation()">
          <button type="button" class="mdrop-btn" onclick="sdToggle('xe_to'); event.stopPropagation();">
            <span id="xe_to_label">UAH</span>
          </button>
          <div class="mdrop-menu">
            <div class="mdrop-head">
              <input id="xe_to_search" placeholder="Поиск валюты..." oninput="onSdSearch('xe_to')" />
            </div>
            <div class="mdrop-body">
              <div class="mdrop-grid" id="xe_to_grid"></div>
            </div>
          </div>
        </div>
      </div>

      <div style="align-self:end">
        <button type="submit">Применить</button>
        <button type="button" onclick="refreshNow()">Обновить</button>
      </div>
    </form>
  </div>

  <!-- Ряд XE + Google Finance -->
  <div class="grid" style="margin-top:16px;">
    <div class="card" id="xe_card">
      <h2 style="margin:0 0 6px;">XE.com <span id="xe_pair" class="chip">—</span></h2>
      <div id="xe_error" class="error" style="display:none"></div>
      <div class="rate" id="xe_price">—</div>
      <div class="muted">
        <span id="xe_ts">—</span>
        · <span id="xe_src" class="chip">—</span>
        · <a id="xe_link" href="#" target="_blank" rel="noopener" style="color:var(--muted);">Открыть в XE</a>
      </div>
      <div style="margin-top:8px;">
        <span class="chip">Спред к Binance: <span id="xe_spread_bin">—</span></span>
        &nbsp; <span class="chip">Спред к Bybit: <span id="xe_spread_byb">—</span></span>
      </div>
    </div>

    <div class="card" id="gf_card">
      <h2 style="margin:0 0 6px;">Google Finance <span id="gf_pair" class="chip"></span></h2>
      <div id="gf_error" class="error" style="display:none"></div>
      <div class="rate" id="gf_price">—</div>
      <div class="muted">
        <span id="gf_ts">—</span>
        · <a id="gf_link" href="#" target="_blank" rel="noopener" style="color:var(--muted);">Открыть котировку</a>
      </div>
      <div style="margin-top:8px;">
        <span class="chip">Спред к Binance: <span id="gf_spread_bin">—</span></span>
        &nbsp; <span class="chip">Спред к Bybit: <span id="gf_spread_byb">—</span></span>
      </div>
    </div>
  </div>

  <!-- Ряд Binance + Bybit -->
  <div class="grid" style="margin-top:16px;">
    <!-- Binance -->
    <div class="card" id="binance_card">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
        <h2 style="margin:0;">Binance</h2>
        <button class="btn-small" type="button" onclick="toggleFilters('binance_filters', this)">Фильтры</button>
      </div>
      <div id="binance_status" class="ok" style="display:none">OK</div>
      <div id="binance_error" class="error" style="display:none"></div>
      <div class="rate" id="binance_avg">—</div>
      <div class="muted" id="binance_prices">—</div>

      <div class="filters" id="binance_filters" style="display:none; border-top:1px dashed var(--border); padding-top:12px;">
        <div class="row">
          <div>
            <label>Верифицированные продавцы</label>
            <select id="merchant_binance">
              <option value="true">Да</option>
              <option value="false">Нет</option>
            </select>
          </div>
          <div>
            <label>Платёжные методы</label>
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
      </div>

      <table>
        <thead><tr><th>#</th><th>Трейдер</th><th>Цена</th><th>Объём</th><th>Мин</th><th>Макс</th></tr></thead>
        <tbody id="binance_tbody"></tbody>
      </table>
    </div>

    <!-- Bybit -->
    <div class="card" id="bybit_card">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px;">
        <h2 style="margin:0;">Bybit</h2>
        <button class="btn-small" type="button" onclick="toggleFilters('bybit_filters', this)">Фильтры</button>
      </div>
      <div id="bybit_status" class="ok" style="display:none">OK</div>
      <div id="bybit_error" class="error" style="display:none"></div>
      <div class="rate" id="bybit_avg">—</div>
      <div class="muted" id="bybit_prices">—</div>

      <div class="filters" id="bybit_filters" style="display:none; border-top:1px dashed var(--border); padding-top:12px;">
        <div class="row">
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
      </div>

      <table>
        <thead><tr><th>#</th><th>Трейдер</th><th>Цена</th><th>Объём</th><th>Мин</th><th>Макс</th></tr></thead>
        <tbody id="bybit_tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
  // Таймеры
  let timer = null;
  const REFRESH_MS = 30000;

  let xeTimer = null;
  const XE_REFRESH_MS = 15000;

  // Кэш последних средних для спредов
  let lastBinanceAvg = null;
  let lastBybitAvg   = null;

  // Multi-select
  let selectedBinance = new Set();
  let selectedBybit   = new Set();
  const tempSelected  = { dd_binance: new Set(), dd_bybit: new Set() };
  const searchState   = { dd_binance: "", dd_bybit: "" };
  let binanceItems = [];
  let bybitItems   = [];

  // XE single-select
  let XE_SYMBOLS = [];
  let xeFrom = 'USD';
  let xeTo   = 'UAH';
  const sdSearch = { xe_from: '', xe_to: '' };

  function fmt(n){ return Number(n).toLocaleString('ru-RU', {minimumFractionDigits:2, maximumFractionDigits:6}); }
  function fmtShort(n){ return Number(n).toLocaleString('ru-RU', {maximumFractionDigits:6}); }

  // ------- Параметры / загрузка -------
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

  // ------- Отрисовка/ошибки -------
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

  // ------- Multi-dropdown -------
  function mdropToggle(ddId){
    const dd = document.getElementById(ddId);
    if (dd.classList.contains('open')){
      closeAndClear(ddId);
      return;
    }
    closeAllDropdowns();
    dd.classList.add('open');
    if (ddId==='dd_binance') tempSelected[ddId] = new Set([...selectedBinance]);
    if (ddId==='dd_bybit')   tempSelected[ddId] = new Set([...selectedBybit]);
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
      if (id.startsWith('dd_')) { // это мульти
        searchState[id] = "";
        const input = document.getElementById(id + '_search');
        if (input) input.value = "";
      }
      if (id.startsWith('xe_')) { // это single
        sdSearch[id] = "";
        const input = document.getElementById(id + '_search');
        if (input) input.value = "";
      }
    });
  }
  document.addEventListener('pointerdown', (e) => {
    const openDd = document.querySelector('.mdrop.open');
    if (!openDd) return;
    if (openDd.contains(e.target)) return;
    closeAllDropdowns();
  }, true);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllDropdowns();
  });

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
  }
  function updateCounters(){
    document.getElementById('dd_binance_count').textContent = String(selectedBinance.size);
    document.getElementById('dd_bybit_count').textContent   = String(selectedBybit.size);
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
      binanceItems = [];
      selectedBinance.clear();
      updateCounters();
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
      bybitItems = [];
      selectedBybit.clear();
      updateCounters();
      return [];
    }
  }

  // ------- XE single-select ------
  async function loadXeSymbols(){
    try{
      const r = await fetch('/api/xe/symbols');
      const js = await r.json();
      XE_SYMBOLS = (js.symbols || []).sort();
      renderSdOptions('xe_from');
      renderSdOptions('xe_to');
      setXeLabels();
    }catch(e){
      XE_SYMBOLS = ['USD','EUR','UAH'];
      renderSdOptions('xe_from');
      renderSdOptions('xe_to');
      setXeLabels();
    }
  }
  function setXeLabels(){
    document.getElementById('xe_from_label').textContent = xeFrom;
    document.getElementById('xe_to_label').textContent   = xeTo;
  }
  function sdToggle(id){
    const el = document.getElementById(id);
    const opened = el.classList.contains('open');
    closeAllDropdowns();
    if (!opened){
      el.classList.add('open');
      renderSdOptions(id);
      const input = document.getElementById(id + '_search');
      if (input){ input.value = sdSearch[id] || ''; input.focus(); }
    }
  }
  function onSdSearch(id){
    const input = document.getElementById(id + '_search');
    sdSearch[id] = (input?.value || '').trim().toLowerCase();
    renderSdOptions(id);
  }
  function renderSdOptions(id){
    const gridId = id + '_grid';
    const grid = document.getElementById(gridId);
    if (!grid) return;
    const q = (sdSearch[id] || '').toLowerCase();
    const list = XE_SYMBOLS.filter(s => s.toLowerCase().includes(q));
    grid.innerHTML = '';
    list.forEach(sym => {
      const btn = document.createElement('div');
      btn.className = 'mdrop-pill';
      btn.textContent = sym;
      btn.title = sym;
      btn.addEventListener('click', () => {
        if (id === 'xe_from') xeFrom = sym;
        if (id === 'xe_to')   xeTo   = sym;
        setXeLabels();
        closeAllDropdowns();
        refreshXENow();
      });
      grid.appendChild(btn);
    });
  }

  // ------- Загрузка данных -------
  async function load(){
    const p = paramsFromUI();
    const url = '/api/rates?' + new URLSearchParams(p).toString();
    const res = await fetch(url);
    let data = null;
    try { data = await res.json(); } catch(e){ data = {ok:false, errors:{fetch:'Bad JSON'}} }

    document.getElementById('ts').textContent = ' • обновлено: ' + new Date().toLocaleTimeString('ru-RU');

    // Google Finance
    document.getElementById('gf_pair').textContent = `${p.asset}-${p.fiat}`;
    const gErr = document.getElementById('gf_error');
    if (data.errors && data.errors.google){
      gErr.style.display = ''; gErr.textContent = 'GF ошибка: ' + data.errors.google;
      document.getElementById('gf_price').textContent = '—';
      document.getElementById('gf_ts').textContent = '—';
      document.getElementById('gf_link').href = '#';
      document.getElementById('gf_spread_bin').textContent = '—';
      document.getElementById('gf_spread_byb').textContent = '—';
    } else if (data.google){
      gErr.style.display = 'none';
      const g = data.google;
      document.getElementById('gf_price').textContent = fmtShort(g.price) + ' ' + p.fiat;
      document.getElementById('gf_ts').textContent = 'TS: ' + new Date(g.ts*1000).toLocaleTimeString('ru-RU');
      document.getElementById('gf_link').href = g.url || '#';
      const s1 = ((data.binance?.avg ?? null) === null) ? null : ((data.binance.avg - g.price) / g.price * 100);
      const s2 = ((data.bybit?.avg ?? null) === null) ? null : ((data.bybit.avg - g.price) / g.price * 100);
      document.getElementById('gf_spread_bin').innerHTML = s1==null ? '—' : ((s1>0?'+':'') + s1.toFixed(2) + '%');
      document.getElementById('gf_spread_byb').innerHTML = s2==null ? '—' : ((s2>0?'+':'') + s2.toFixed(2) + '%');
    }

    // Binance
    const bErr = document.getElementById('binance_error');
    const bOk  = document.getElementById('binance_status');
    if (data.errors && data.errors.binance){
      bErr.style.display = ''; bErr.textContent = 'Ошибка: ' + data.errors.binance;
      bOk.style.display = 'none';
      document.getElementById('binance_avg').textContent = '—';
      document.getElementById('binance_prices').textContent = '—';
      document.getElementById('binance_tbody').innerHTML = '';
      lastBinanceAvg = null;
    } else if (data.binance){
      bErr.style.display = 'none'; bOk.style.display = '';
      const d = data.binance;
      document.getElementById('binance_avg').textContent = (d.avg!=null? fmt(d.avg):'—') + ' ' + p.fiat;
      document.getElementById('binance_prices').textContent = d.prices && d.prices.length >= 3 ? ('#3–5: ' + d.prices.slice(2,5).map(fmt).join(' • ')) : '—';
      const tb = document.getElementById('binance_tbody'); tb.innerHTML = '';
      (d.items||[]).forEach((it, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${i+1}</td><td>${it.name||'-'}</td><td>${fmt(it.price)}</td><td>${it.volume??'-'}</td><td>${it.min??'-'}</td><td>${it.max??'-'}</td>`;
        tb.appendChild(tr);
      });
      lastBinanceAvg = d.avg ?? null;
    }

    // Bybit
    const yErr = document.getElementById('bybit_error');
    const yOk  = document.getElementById('bybit_status');
    if (data.errors && data.errors.bybit){
      yErr.style.display = ''; yErr.textContent = 'Ошибка: ' + data.errors.bybit;
      yOk.style.display = 'none';
      document.getElementById('bybit_avg').textContent = '—';
      document.getElementById('bybit_prices').textContent = '—';
      document.getElementById('bybit_tbody').innerHTML = '';
      lastBybitAvg = null;
    } else if (data.bybit){
      yErr.style.display = 'none'; yOk.style.display = '';
      const d = data.bybit;
      document.getElementById('bybit_avg').textContent = (d.avg!=null? fmt(d.avg):'—') + ' ' + p.fiat;
      document.getElementById('bybit_prices').textContent = d.prices && d.prices.length >= 3 ? ('#3–5: ' + d.prices.slice(2,5).map(fmt).join(' • ')) : '—';
      const tb = document.getElementById('bybit_tbody'); tb.innerHTML = '';
      (d.items||[]).forEach((it, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${i+1}</td><td>${it.name||'-'}</td><td>${fmt(it.price)}</td><td>${it.volume??'-'}</td><td>${it.min??'-'}</td><td>${it.max??'-'}</td>`;
        tb.appendChild(tr);
      });
      lastBybitAvg = d.avg ?? null;
    }

    // Пересчитать спреды для XE (если уже получен)
    if (window.__lastXePrice != null){
      const base = window.__lastXePrice;
      const s1 = (lastBinanceAvg==null) ? null : ((lastBinanceAvg - base) / base * 100);
      const s2 = (lastBybitAvg==null)   ? null : ((lastBybitAvg - base) / base * 100);
      document.getElementById('xe_spread_bin').innerHTML = s1==null ? '—' : ((s1>0?'+':'') + s1.toFixed(2) + '%');
      document.getElementById('xe_spread_byb').innerHTML = s2==null ? '—' : ((s2>0?'+':'') + s2.toFixed(2) + '%');
    }
  }

  // ------- XE: отдельная загрузка -------
  window.__lastXePrice = null;

  function xePairFromUI(){
    return { from: xeFrom, to: xeTo };
  }

  async function loadXE(){
    const pr = xePairFromUI();
    const err = document.getElementById('xe_error');

    if (!pr || !pr.from || !pr.to || pr.from === pr.to){
      err.style.display = '';
      err.textContent = 'Выберите корректные XE From и XE To (разные валюты).';
      document.getElementById('xe_pair').textContent = '—';
      document.getElementById('xe_price').textContent = '—';
      document.getElementById('xe_ts').textContent = '—';
      document.getElementById('xe_src').textContent = '—';
      document.getElementById('xe_link').href = '#';
      document.getElementById('xe_spread_bin').textContent = '—';
      document.getElementById('xe_spread_byb').textContent = '—';
      window.__lastXePrice = null;
      return;
    }

    const url = '/api/xe?' + new URLSearchParams({amount:'1', from: pr.from, to: pr.to}).toString();
    try{
      const r = await fetch(url);
      const js = await r.json();

      document.getElementById('xe_pair').textContent = `${pr.from}-${pr.to}`;

      if (!js.ok){
        err.style.display = '';
        err.textContent = 'Ошибка XE: ' + (js.error || 'unknown');
        document.getElementById('xe_price').textContent = '—';
        document.getElementById('xe_ts').textContent = '—';
        document.getElementById('xe_src').textContent = '—';
        document.getElementById('xe_link').href = '#';
        window.__lastXePrice = null;
        return;
      }

      err.style.display = 'none';
      const d = js.data;
      document.getElementById('xe_price').textContent = fmtShort(d.price) + ' ' + pr.to;
      document.getElementById('xe_ts').textContent = 'TS: ' + new Date(d.ts*1000).toLocaleTimeString('ru-RU');
      document.getElementById('xe_src').textContent = (d.source || 'n/a') + (d.hydrated ? ' · hydrated' : '');
      document.getElementById('xe_link').href = d.url || '#';

      window.__lastXePrice = d.price;

      const base = d.price;
      const s1 = (lastBinanceAvg==null) ? null : ((lastBinanceAvg - base) / base * 100);
      const s2 = (lastBybitAvg==null)   ? null : ((lastBybitAvg - base) / base * 100);
      document.getElementById('xe_spread_bin').innerHTML = s1==null ? '—' : ((s1>0?'+':'') + s1.toFixed(2) + '%');
      document.getElementById('xe_spread_byb').innerHTML = s2==null ? '—' : ((s2>0?'+':'') + s2.toFixed(2) + '%');

    }catch(e){
      err.style.display = '';
      err.textContent = 'Ошибка сети/парсинга XE';
      window.__lastXePrice = null;
    }
  }

  // ------- Применить/обновить -------
  function refreshNow(){
    load();
    if (timer) clearInterval(timer);
    timer = setInterval(load, REFRESH_MS);
  }
  function refreshXENow(){
    loadXE();
    if (xeTimer) clearInterval(xeTimer);
    xeTimer = setInterval(loadXE, XE_REFRESH_MS);
  }
  function apply(ev){ ev.preventDefault(); applyFiltersFromCurrent(); }
  function applyFiltersFromCurrent(){
    refreshNow();
    refreshXENow();
    const p = paramsFromUI();
    history.replaceState(null, '', '?' + new URLSearchParams(p).toString());
  }

  // --- wiring для мультидропа подтверждение/сброс
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
        applyFiltersFromCurrent();
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

  // Инициализация
  window.addEventListener('DOMContentLoaded', async () => {
    // из URL
    const q = new URLSearchParams(location.search);
    for (const id of ['asset','fiat','side','amount']){
      const v = q.get(id); if (v!==null) document.getElementById(id).value = v;
    }

    // восстановление мультивыбора из URL
    const bcsv = q.get('paytypes_binance'); if (bcsv){ bcsv.split(',').forEach(x => x && selectedBinance.add(x)); }
    const ycsv = q.get('payments_bybit');   if (ycsv){ ycsv.split(',').forEach(x => x && selectedBybit.add(x)); }

    // XE: начальные значения (если в URL есть from/to — опционально)
    const fromURL = q.get('xe_from'); if (fromURL) xeFrom = fromURL.toUpperCase();
    const toURL   = q.get('xe_to');   if (toURL)   xeTo   = toURL.toUpperCase();

    // навесим обработчики drop-меню
    wireDropdown('dd_binance');
    wireDropdown('dd_bybit');

    await loadXeSymbols();
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

@app.route("/healthz")
def healthz():
    return "ok"

if __name__ == "__main__":
    # Запуск: (обязательно с валидными куками в окружении, если нужно)
    # set BINANCE_COOKIE=...
    # set BYBIT_COOKIE=...
    # python p2p_dashboard.py
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
