# p2p_dashboard.py
# Обновления:
# - Дропдауны скрыты по умолчанию, открываются только по клику "Выбрать методы"
# - Закрытие по повторному клику, по клику вне и по Esc
# - "Подтвердить"/"Сбросить": сначала запрос/обновление, затем закрытие меню
# - Поиск и множественный выбор плитками, зелёные акценты
# - Bybit методы берутся из bybit_payment_methods.txt (формат: === UAH ===, далее "id name")

import os
import time
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# ------------------ Куки / заголовки ------------------
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

# ------------------ Утилиты ------------------
def _avg_3_5(prices):
    if len(prices) >= 5:
        return round(sum(prices[2:5]) / 3.0, 6)
    return None

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
    data = js["data"]
    items, prices = [], []
    for ad in data[:5]:
        adv = ad.get("adv", {})
        seller = ad.get("advertiser", {}).get("nickName") or "-"
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
    return {"items": items, "prices": prices, "avg": _avg_3_5(prices), "raw": data}

def discover_binance_paytypes(asset="USDT", fiat="UAH", side="SELL", amount="20000", merchant=True, pages=3, rows=20):
    seen = {}
    for p in range(1, pages+1):
        payload = {
            "asset": asset, "fiat": fiat, "merchantCheck": bool(merchant),
            "page": p, "payTypes": [], "publisherType": None,
            "rows": int(rows), "tradeType": side, "transAmount": str(amount),
        }
        r = requests.post(BINANCE_URL, headers=BINANCE_HEADERS, json=payload, timeout=15)
        if r.status_code != 200: break
        js = r.json()
        if js.get("code") != "000000": break
        data = js.get("data", [])
        if not data: break
        for ad in data:
            adv = ad.get("adv", {})
            for tm in adv.get("tradeMethods", []) or []:
                ident = (tm.get("identifier") or tm.get("payType") or "").strip()
                name  = (tm.get("tradeMethodName") or tm.get("name") or ident).strip()
                if ident: seen[ident] = name
            for ident in ad.get("payTypes", []) or []:
                if ident and ident not in seen: seen[ident] = ident
    items = [{"id": k, "name": v} for k, v in seen.items()]
    items.sort(key=lambda x: (x["name"].lower(), x["id"]))
    return items

# ------------------ Bybit ------------------
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
    data = result.get("items", [])[:5]

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
    return {"items": items, "prices": prices, "avg": _avg_3_5(prices)}

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

    # 1) строго берём data-last-price
    if blk and blk.has_attr("data-last-price"):
        return float(blk["data-last-price"]), url

    # 2) fallback: видимый текст (может быть сломан локалью — используем только при отсутствии атрибута!)
    if blk:
        node = blk.select_one("div.YMlKec.fxKbKc") or blk.select_one("div.YMlKec")
        if node and node.text:
            return _num_to_float(node.get_text(" ", strip=True)), url

    # 3) ещё один грубый запасной вариант
    m = re.findall(r'data-last-price="([^"]+)"', r.text)
    if m:
        return float(m[-1]), url

    # 4) совсем крайний случай
    node = soup.select_one("div.YMlKec.fxKbKc") or soup.select_one("div.YMlKec")
    if node and node.text:
        return _num_to_float(node.get_text(" ", strip=True)), url

    raise RuntimeError("GF: не удалось извлечь цену")

def _gf_only_price(asset: str, fiat: str) -> float:
    p, _ = _gf_price_direct(asset, fiat)
    return p

def fetch_gf(asset: str, fiat: str):
    A, F = asset.upper(), fiat.upper()

    # прямое чтение
    direct_price, url = _gf_price_direct(A, F)

    # кросс через USD для контроля
    cross = None
    try:
        if A != "USD" and F != "USD":
            a_usd = _gf_only_price(A, "USD")
            usd_f = _gf_only_price("USD", F)
            cross = a_usd * usd_f
    except Exception:
        cross = None

    # проверка разумности диапазона (очень широкая)
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
            # если сильно отличается от кросса (>25%) — доверяем кроссу
            rel = abs(chosen - cross) / max(cross, 1e-12)
            if rel > 0.25:
                chosen = cross

    # спец-проверка для стейблов
    if A in {"USDT", "USDC", "DAI", "TUSD", "USD"} and F in {"UAH", "USD", "EUR"}:
        if not (0.01 < chosen < 1000) and cross is not None and (0.01 < cross < 1000):
            chosen = cross

    return {"pair": f"{A}-{F}", "price": float(chosen), "url": url, "ts": int(time.time())}

# ------------------ Bybit payments из txt ------------------
BYBIT_PAYMENTS_MAP = {}

def _load_bybit_payments():
    path_local = os.path.join(os.path.dirname(__file__), "bybit_payment_methods.txt")
    path_alt   = "/mnt/data/bybit_payment_methods.txt"
    path = path_local if os.path.exists(path_local) else (path_alt if os.path.exists(path_alt) else None)
    if not path: return
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

# ------------------ Единый API ------------------
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
        out["google"] = fetch_gf(asset, fiat)
    except Exception as e:
        errors["google"] = str(e)

    try:
        out["binance"] = fetch_binance(asset, fiat, side, paytypes_binance, amount, rows=10, merchant=merchant_binance)
    except Exception as e:
        errors["binance"] = str(e)

    try:
        out["bybit"] = fetch_bybit(asset, fiat, side, bybit_payments, amount, rows=10, verified=verified_bybit)
    except Exception as e:
        errors["bybit"] = str(e)

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

# ------------------ Страница ------------------
PAGE = """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<title>P2P Dashboard: Binance • Bybit • Google Finance</title>
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

  /* Multi-dropdown */
  .mdrop { position: relative; display:inline-block; width:100%; }
  .mdrop-btn { width:100%; text-align:left; display:flex; align-items:center; justify-content:space-between; gap:8px; }
  .mdrop-btn .count { color:var(--muted); font-size:12px; }
  .mdrop-menu {
    position:absolute; z-index:20; margin-top:6px; min-width:320px; max-width:520px; max-height:420px;
    background:#0f1218; border:1px solid var(--border); border-radius:12px; box-shadow:0 20px 40px rgba(0,0,0,.45);
    display:none; overflow:hidden; flex-direction:column; /* flex будет при .open */
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

  <!-- Google Finance -->
  <div class="card" id="gf_card" style="margin-top:12px;">
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
            <label>Платёжные метод</label>
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
            <!-- без чипсов -->
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
            <label>Платёжные метод </label>
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
  let timer = null;
  const REFRESH_MS = 30000;

  // Выборы
  let selectedBinance = new Set();
  let selectedBybit   = new Set();
  const tempSelected  = { dd_binance: new Set(), dd_bybit: new Set() };

  // Поиск
  const searchState = { dd_binance: "", dd_bybit: "" };

  // Кэши справочников
  let binanceItems = [];
  let bybitItems   = [];

  // ---------- Фильтры карточек ----------
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

  // ---------- Выпадашки ----------
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
      searchState[id] = "";
      const input = document.getElementById(id + '_search');
      if (input) input.value = "";
    });
  }

  // Закрытие по клику вне — capture, чтобы срабатывало надёжно
  document.addEventListener('pointerdown', (e) => {
    const openDd = document.querySelector('.mdrop.open');
    if (!openDd) return;
    if (openDd.contains(e.target)) return; // клики внутри меню не закрывают
    closeAllDropdowns();
  }, true);

  // Закрытие по Esc
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllDropdowns();
  });

  // ---------- Поиск ----------
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

  // ---------- Справочники ----------
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

  // ---------- Параметры / загрузка ----------
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

  function fmt(n){ return Number(n).toLocaleString('ru-RU', {minimumFractionDigits:2, maximumFractionDigits:6}); }
  function fmtShort(n){ return Number(n).toLocaleString('ru-RU', {maximumFractionDigits:6}); }

  async function load(){
    const p = paramsFromUI();
    const url = '/api/rates?' + new URLSearchParams(p).toString();
    const res = await fetch(url);
    let data = null;
    try { data = await res.json(); } catch(e){ data = {ok:false, errors:{fetch:'Bad JSON'}} }

    document.getElementById('ts').textContent = ' • обновлено: ' + new Date().toLocaleTimeString('ru-RU');

    // GF
    const gErr = document.getElementById('gf_error');
    document.getElementById('gf_pair').textContent = `${p.asset}-${p.fiat}`;
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
    } else if (data.binance){
      bErr.style.display = 'none'; bOk.style.display = '';
      const d = data.binance;
      document.getElementById('binance_avg').textContent = (d.avg!=null? fmt(d.avg):'—') + ' ' + p.fiat;
      document.getElementById('binance_prices').textContent = d.prices && d.prices.length ? ('#3–5: ' + d.prices.slice(2,5).map(fmt).join(' • ')) : '—';
      const tb = document.getElementById('binance_tbody'); tb.innerHTML = '';
      (d.items||[]).forEach((it, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${i+1}</td><td>${it.name||'-'}</td><td>${fmt(it.price)}</td><td>${it.volume??'-'}</td><td>${it.min??'-'}</td><td>${it.max??'-'}</td>`;
        tb.appendChild(tr);
      });
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
    } else if (data.bybit){
      yErr.style.display = 'none'; yOk.style.display = '';
      const d = data.bybit;
      document.getElementById('bybit_avg').textContent = (d.avg!=null? fmt(d.avg):'—') + ' ' + p.fiat;
      document.getElementById('bybit_prices').textContent = d.prices && d.prices.length ? ('#3–5: ' + d.prices.slice(2,5).map(fmt).join(' • ')) : '—';
      const tb = document.getElementById('bybit_tbody'); tb.innerHTML = '';
      (d.items||[]).forEach((it, i) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${i+1}</td><td>${it.name||'-'}</td><td>${fmt(it.price)}</td><td>${it.volume??'-'}</td><td>${it.min??'-'}</td><td>${it.max??'-'}</td>`;
        tb.appendChild(tr);
      });
    }
  }

  function apply(ev){ ev.preventDefault(); applyFiltersFromCurrent(); }
  function applyFiltersFromCurrent(){
    refreshNow();
    const p = paramsFromUI();
    history.replaceState(null, '', '?' + new URLSearchParams(p).toString());
  }
  function refreshNow(){ load(); if (timer) clearInterval(timer); timer = setInterval(load, REFRESH_MS); }
  // --- Делегирование кликов внутри меню
function wireDropdown(ddId){
  const root = document.getElementById(ddId);
  if (!root) return;
  const menu = root.querySelector('.mdrop-menu');
  if (!menu || menu.__wired) return;

  menu.addEventListener('click', (e) => {
    e.stopPropagation();

    // Подтвердить — применяем, грузим, закрываем
    if (e.target.closest('.js-confirm')){
      if (ddId==='dd_binance') selectedBinance = new Set([...tempSelected[ddId]]);
      if (ddId==='dd_bybit')   selectedBybit   = new Set([...tempSelected[ddId]]);
      updateCounters();
      applyFiltersFromCurrent();  // 1) отправить запрос/обновить
      closeAllDropdowns();        // 2) закрыть меню
      return;
    }

    // Сбросить — только очистить временный выбор и UI, без запроса и закрытия
    if (e.target.closest('.js-reset')){
      tempSelected[ddId] = new Set();  // очищаем временный выбор
      renderDropdownOptions(ddId);     // снимаем подсветку плиток мгновенно
      // Обновить счетчик внутри кнопки (показываем temp.size)
      const cntSpan = document.getElementById(ddId === 'dd_binance' ? 'dd_binance_count' : 'dd_bybit_count');
      if (cntSpan) cntSpan.textContent = '0';
      return;
    }
  });

  menu.__wired = true;
}
  // Инициализация
  window.addEventListener('DOMContentLoaded', async () => {
    // Свернуть все дропдауны на старте (страховка)
    closeAllDropdowns();

    // Параметры из URL -> форма
    const q = new URLSearchParams(location.search);
    for (const id of ['asset','fiat','side','amount']){
      const v = q.get(id); if (v!==null) document.getElementById(id).value = v;
      wireDropdown('dd_binance');
      wireDropdown('dd_bybit');
      refreshNow();
    }
    const bcsv = q.get('paytypes_binance'); if (bcsv){ bcsv.split(',').forEach(x => x && selectedBinance.add(x)); }
    const ycsv = q.get('payments_bybit');   if (ycsv){ ycsv.split(',').forEach(x => x && selectedBybit.add(x)); }

    await loadBinancePaytypes();
    await loadBybitPayments();
    updateCounters();

    // Глобальные фильтры — перезагрузка данных
    document.getElementById('asset').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('fiat').addEventListener('change', () => { loadBinancePaytypes(); loadBybitPayments(); refreshNow(); });
    document.getElementById('side').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('amount').addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });

    // Мгновенно реагируем на переключатели
    document.getElementById('merchant_binance')?.addEventListener('change', () => { loadBinancePaytypes(); refreshNow(); });
    document.getElementById('verified_bybit')?.addEventListener('change', () => { refreshNow(); });

    refreshNow();
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
    app.run(host="0.0.0.0", port=5000, debug=True)

