
# p2p_dashboard.py
# Единая страница: сверху панель фильтров, ниже 2 колонки (Binance / Bybit).
# Усреднение по объявлениям №3–5, вывод топ-5 строк.
# Поддержка куков через переменные окружения BINANCE_COOKIE / BYBIT_COOKIE.

import os
import time
import json
import requests
from flask import Flask, request, jsonify, Response, render_template_string

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# ------------------ Конфиг / куки ------------------
BINANCE_COOKIE = os.getenv("BINANCE_COOKIE", "bnc-uuid=24e155f9-acda-4066-940b-4885f4bb5d9b; ref=1121500771; lang=ru-UA; language=ru-UA; "
    "BNC_FV_KEY=3352998e0fcbaf35a8c1adc76cbdf4f92046cec1; se_gd=xkBEAQR9QBKDwhbYQUwogZZUwUA0QBXVlsSJYV091NRWgCFNWV9V1; "
    "se_gsd=azM2GhpVJiklM1syJyUyGggnEAcODgVUVFVKWlFSVlNXElNT1; currentAccount=; BNC-Location=UA; "
    "fiat-prefer-currency=UAH; common_fiat=%7B%22fiat%22%3A%22UAH%22%7D; userPreferredCurrency=USD_USD; theme=dark; "
    "BNC_FV_KEY_T=101-5BcGU%2B7Q1RKn0%2FY2vL8HgC2L2xqiMTzra6691PF3IFbQYt7qfB2Yqcpd0IuJlgxPGAXg%2FpbITTLagrT66aKUYg%3D%3D-NL50styO1mk%2BRzolvgD8Kg%3D%3D-03; "
    "BNC_FV_KEY_EXPIRE=1752798024475; se_sd=BQOBlUVwVBaU1cXcRDVkgZZFwBgwQERUVAHFQWk91NTVAF1NWVUV1; "
    "s9r1=A249108022543F7B83C49D5E64EFAA72; r20t=web.F830508C564F161CCEAF32E6152960C1; r30t=1; cr00=2ED474164572CFD675135602B57A1F80; "
    "d1og=web.320158455.046C0A4D0E9285D8658ECFD8924A9C5B; r2o1=web.320158455.B67C9FD63EF34576A7E1C7FA56440E71; "
    "f30l=web.320158455.D7B6AB30BB93784A710A5F4093652523; logined=y; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%22320158455%22%2C%22first_id%22%3A%221980ece448a22b-0e104b4a3c8a8-26011151-3686400-1980ece448b17c0%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%2C%22%24latest_referrer%22%3A%22%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTk4MGVjZTQ0OGEyMmItMGUxMDRiNGEzYzhhOC0yNjAxMTE1MS0zNjg2NDAwLTE5ODBlY2U0NDhiMTdjMCIsIiRpZGVudGl0eV9sb2dpbl9pZCI6IjMyMDE1ODQ1NSJ9%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%24identity_login_id%22%2C%22value%22%3A%22320158455%22%7D%2C%22%24device_id%22%3A%2219812922cb61f0-0f815e9aa74ba48-26011151-3686400-19812922cb7f7f%22%7D; "
    "p20t=web.320158455.E27540F2D9614B5553202B2505F87127; OptanonConsent=isGpcEnabled=0&datestamp=Thu+Jul+17+2025+22%3A11%3A25+GMT%2B0300+(%D0%92%D0%BE%D1%81%D1%82%D0%BE%D1%87%D0%BD%D0%B0%D1%8F+%D0%95%D0%B2%D1%80%D0%BE%D0%BF%D0%B0%2C+%D0%BB%D0%B5%D1%82%D0%BD%D0%B5%D0%B5+%D0%B2%D1%80%D0%B5%D0%BC%D1%8F)&version=202506.1.0&browserGpcFlag=0&isIABGlobal=false&hosts=&consentId=6d9ed745-85d2-457b-8d07-1040687ff23d&interactionCount=1&isAnonUser=1&landingPath=NotLandingPage&groups=C0001%3A1%2CC0003%3A1%2CC0004%3A0%2CC0002%3A1&AwaitingReconsent=false")
BYBIT_COOKIE   = os.getenv("BYBIT_COOKIE", """_ym_uid=1742585307975664233; _ym_d=1742585307; _abck=4EB8FFFE5FB66A20DA006F9F6774C9F9~0~YAAQDQxAFwKjj7CVAQAAFVD0vg0UQGnDQqqTBokasujKGB8D9RCNmT7vk+ldR+3B0sOTCaQWZHTDMwh+qDkBGXQelkdx2dxr8P2r5vtXEviP81hOX4X3TOgHmtY4seb3AyuO9rsXitcwldbgxrzbwD/T1ZnVxxSy30tnOT8mXwBasiFJOdOJWUP2GkEIuG0f2GoeS6VtAg40Wv+lAM3IbpPNRTw92F83bPWjIsaRJCETa55rvCakkUWeLnLDZOcYxMTqI3Ka8w+cySh8WJrEl9J3k5UDpk+Me0KPt2bCZtgsABsQYHfeJy/sMMCADA6qpGKB8mX9mhrH42jPvVOQtbK7zoxKbxvrP/IXbK1RnEJ/O+6UTw8xY+djjxg/087JBXDDaO3pC1cvLiWSj1Sja41vFnv/9fFWrhj8+BKl7gobhXPgeEgBFzXcVdlO9HF+2/brPWRZZbAsWNNqQ3Gd7g==~-1~-1~-1; _by_l_g_d=decd7e79-db40-af29-2ee9-4dd102e2e7a2; deviceId=ef9cacc7-a75b-3ca3-4588-1be6dd463c96; _ga=GA1.1.1823559572.1755113755; _tt_enable_cookie=1; _ttp=01K2JEX4FKY4K10RWFZ7N999G0_.tt.1; BYBIT_REG_REF_prod={"lang":"ru-UA","g":"decd7e79-db40-af29-2ee9-4dd102e2e7a2","referrer":"www.bybit.com/ru-RU/fiat/trade/otc?token=USDT&fiat=UAH&side=1&amount=20000&verifiedOnly=true&t=1755725246","source":"bybit.com","medium":"other","url":"https://www.bybit.com/ru-RU/p2p?token=USDT&fiat=UAH&side=1&amount=20000&verifiedOnly=true&t=1755725246","last_refresh_time":"Wed, 20 Aug 2025 21:30:14 GMT","ext_json":{"dtpid":null}}; tx_token_current=BNE; _ym_isad=1; cookies_uuid_report=0aed6f3c-45ae-4625-a5bb-efb2894179e0; first_collect=true; EO-Bot-Session=-n3l54HSyiMxKh-JfsBVAkszTpeFm6JfFu5tSnY3ce1H-UxrJJ_9o9tew34hXyoP; EO-Bot-SessionId=2964890993601779914; sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%22500846094%22%2C%22first_id%22%3A%2219882adf8e58ae-02a5663075fde4a-26011151-3686400-19882adf8e6157b%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E5%BC%95%E8%8D%90%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC%22%2C%22%24latest_referrer%22%3A%22https%3A%2F%2Fchatgpt.com%2F%22%2C%22_a_u_v%22%3A%220.0.6%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTk4ODJhZGY4ZTU4YWUtMDJhNTY2MzA3NWZkZTRhLTI2MDExMTUxLTM2ODY0MDAtMTk4ODJhZGY4ZTYxNTdiIiwiJGlkZW50aXR5X2xvZ2luX2lkIjoiNTAwODQ2MDk0In0%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%24identity_login_id%22%2C%22value%22%3A%22500846094%22%7D%7D; by_token_print=2a5df07cf6m0zgfdtem129scd1994a0c2; deviceCodeExpire=1755735912065; _gcl_au=1.1.648850041.1755113755.1864717054.1755735931.1755735931; secure-token=eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjo1MDA4NDYwOTQsImIiOjAsInAiOjMsInVhIjoiIiwiZ2VuX3RzIjoxNzU1NzM1OTM3LCJleHAiOjE3NTU5OTUxMzcsIm5zIjoiIiwiZXh0Ijp7IlN0YXRpb24tVHlwZSI6IiIsIm1jdCI6IjE3NTU3MDc3ODMiLCJzaWQiOiJCWUJJVCJ9LCJkIjpmYWxzZSwic2lkIjoiQllCSVQifQ.TOuGbPYfwNjiR45dYkr3lXwSsBhocfOHwZTplnPqmIuPOQcUQVRpYsniIx_N6myq_XJ0S83W6QqCY76y8rklfQ; _by_l_g_d=decd7e79-db40-af29-2ee9-4dd102e2e7a2; __rtbh.uid=%7B%22eventType%22%3A%22uid%22%2C%22id%22%3A%22undefined%22%2C%22expiryDate%22%3A%222026-08-21T00%3A25%3A52.222Z%22%7D; __rtbh.lid=%7B%22eventType%22%3A%22lid%22%2C%22id%22%3A%22LEInhX0O0UgsKJzwAIJG%22%2C%22expiryDate%22%3A%222026-08-21T00%3A25%3A52.222Z%22%7D; EO-Bot-Token=t04GaLcA_AU2oqxk6ri6Bcnp3kfZSIHwk5BOJW2OlV7KJkZsbXXp-b6PKPxHqCRfavjA0GTFAq4EinVsZzouCL2PJe6-19rbd-wRE04ivLNZTvbHoavYFuU1RkRkg9fH3Rs2TcyPImUO8Gynw6hI3Wq-G3VFduh_hCkZL7hP-x32OhHuFjJjiyjfk6YNAfoIJ13xjIaiV2s_Y25RH7USCNQFtgdWaVxs1uEYuPrqI9HNGeqEm7wMtGU9gH-aqXqXb56TjSt5_b8eGMf9DsEh34dlKGtLp4xtO2q1UVNQC2gPNQTJaG7NXkSHv8D8lBHqVn55kMaGFjc_EAOkMfrsYfm5AScyJVDBu8V4RnB4UMDWkXzLTn_VOm0LlX1jlZWjZcX3LgtNGZuKr8*; trace_id_report=876e5a8d-efe0-4dd0-b9a1-24560bddf285; _ga_SPS4ND2MGC=GS2.1.s1755735838$o5$g1$t1755736781$j59$l0$h0; ttcsid=1755735917840::eGxBDPy7q6FwAoKKW4Ru.4.1755736781650; tx_token_time=1755736781861; trace_id_time=1755736781946; ttcsid_CMEEMQRC77UBHLCRLFPG=1755735917840::AYjyla4xpsz6_e8I8HOb.4.1755736782062""")

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

# ------------------ Вспомогательные ------------------
def _avg_3_5(prices):
    if len(prices) >= 5:
        s = sum(prices[2:5]) / 3.0
        return round(s, 6)
    return None

def _fmt_float(x):
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x).replace(",", "."))
        except Exception:
            return None

# ------------------ Binance fetch ------------------
def fetch_binance(asset="USDT", fiat="UAH", side="SELL", pay_type="", amount="20000", rows=10, merchant=True):
    """
    side: SELL = вы продаёте актив, BUY = вы покупаете актив
    pay_type: строка (например MONOBANK). Можно пусто — без фильтра.
    amount: str|int
    """
    payload = {
        "asset": asset,
        "fiat": fiat,
        "merchantCheck": bool(merchant),
        "page": 1,
        "payTypes": [pay_type] if pay_type else [],
        "publisherType": None,
        "rows": int(rows),
        "tradeType": side,            # SELL / BUY
        "transAmount": str(amount),
    }
    r = requests.post(BINANCE_URL, headers=BINANCE_HEADERS, json=payload, timeout=15)
    r.raise_for_status()
    js = r.json()
    if js.get("code") != "000000" or "data" not in js:
        raise RuntimeError(f"Binance API error: {js}")

    data = js["data"][:5]  # первые 5 объявлений
    items, prices = [], []
    for ad in data:
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

    avg = _avg_3_5(prices)
    return {"items": items, "prices": prices, "avg": avg}

# ------------------ Bybit fetch ------------------
def fetch_bybit(token="USDT", fiat="UAH", side="SELL", payments=None, amount="20000", rows=10, verified=False):
    """
    side: SELL / BUY -> конвертируем в 0/1 для Bybit
    payments: список строк. Для Bybit часто используются числовые идентификаторы методов (например '1','43',...),
              можно передать пустой список/None — без фильтра.
    verified: True -> authMaker=True
    """
    side_map = {"SELL": "0", "BUY": "1"}
    payload = {
        "tokenId": token,
        "currencyId": fiat,
        "payment": payments or [],
        "side": side_map.get(side.upper(), "1"),
        "size": str(rows),
        "page": "1",
        "amount": str(amount),
        "authMaker": bool(verified),
        "canTrade": False,
        "shieldMerchant": False,
        "reputation": False,
        "country": ""
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

    avg = _avg_3_5(prices)
    return {"items": items, "prices": prices, "avg": avg}

# ------------------ API ------------------
@app.route("/api/rates")
def api_rates():
    """
    Единая точка, читает общие фильтры и возвращает объект {binance:{...}, bybit:{...}}
    Параметры:
      asset=USDT
      fiat=UAH
      side=SELL|BUY
      amount=20000
      merchant=true|false        (для Binance)
      verified=true|false        (для Bybit)
      payment=...                (для Binance это payType строка, для Bybit — список через запятую)
    """
    asset    = request.args.get("asset", "USDT").upper()
    fiat     = request.args.get("fiat", "UAH").upper()
    side     = request.args.get("side", "SELL").upper()
    amount   = request.args.get("amount", "20000")
    merchant = request.args.get("merchant", "true").lower() == "true"
    verified = request.args.get("verified", "false").lower() == "true"
    payment  = request.args.get("payment", "").strip()

    # Для Binance — один payType (строка)
    binance_paytype = payment if payment else ""

    # Для Bybit — список (если пользователь указал через запятую)
    bybit_payments = []
    if payment:
        # Разрешим как числа (идентификаторы), так и любые строки
        bybit_payments = [p.strip() for p in payment.split(",") if p.strip()]

    out = {"binance": None, "bybit": None}
    errors = {}

    try:
        out["binance"] = fetch_binance(asset, fiat, side, binance_paytype, amount, rows=10, merchant=merchant)
    except Exception as e:
        errors["binance"] = str(e)

    try:
        out["bybit"] = fetch_bybit(asset, fiat, side, bybit_payments, amount, rows=10, verified=verified)
    except Exception as e:
        errors["bybit"] = str(e)

    return jsonify({
        "ok": True,
        "params": {
            "asset": asset, "fiat": fiat, "side": side,
            "amount": amount, "merchant": merchant, "verified": verified,
            "payment": payment
        },
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
<title>P2P Dashboard: Binance & Bybit</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: dark light; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:0; padding:24px; background:#0b0d12; color:#e6e9ef; }
  .wrap { max-width: 1200px; margin: 0 auto; }
  .card { background:#12151c; border:1px solid #242a36; border-radius:16px; padding:16px; }
  h1 { margin:0 0 16px; font-size: 22px; font-weight:700; }
  .muted { color:#9aa4b2; font-size: 12px; }
  .row { display:flex; gap:12px; flex-wrap: wrap; margin: 14px 0; }
  .row > * { flex: 1 1 180px; }
  label { display:block; font-size:12px; color:#9aa4b2; margin-bottom:6px; }
  input, select { width:100%; padding:10px 12px; border-radius:10px; border:1px solid #2a3140; background:#0f1218; color:#e6e9ef; }
  button { padding:10px 14px; border-radius:10px; border:1px solid #2a3140; background:#1a2130; color:#e6e9ef; cursor:pointer; }
  button:hover { background:#20283a; }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-top: 16px; }
  .rate { font-size: 34px; font-weight:700; margin: 6px 0 8px; }
  table { width:100%; border-collapse: collapse; margin-top: 10px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #222a38; font-size: 14px; }
  th { color:#9aa4b2; font-weight:600; font-size:12px; }
  .error { background:#311319; color:#ffb3c0; padding:10px 12px; border:1px solid #51212b; border-radius:10px; margin-top: 8px; }
  .ok { background:#122217; color:#b8ffcf; padding:6px 10px; border-radius:10px; display:inline-block; margin-top: 8px; }
  @media (max-width: 900px){ .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>P2P Dashboard • Binance & Bybit <span class="muted" id="ts"></span></h1>

  <div class="card">
    <form id="filters" class="row" onsubmit="apply(event)">
      <div>
        <label>Актив</label>
        <select id="asset">
          <option>USDT</option>
          <option>BTC</option>
          <option>ETH</option>
          <option>BNB</option>
          <option>SOL</option>
          <option>USDC</option>
        </select>
      </div>
      <div>
        <label>Фиат</label>
        <select id="fiat">
          <option>UAH</option>
          <option>USD</option>
          <option>EUR</option>
          <option>RUB</option>
          <option>KZT</option>
          <option>TRY</option>
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
      <div>
        <label>Платёжный метод</label>
        <input id="payment" placeholder="Напр.: MONOBANK (Binance) или '1,43' (Bybit)" />
      </div>
      <div>
        <label>Верифицированные/Мерчанты</label>
        <select id="verified">
          <option value="true">Да</option>
          <option value="false" selected>Нет</option>
        </select>
        
      </div>
      <div style="align-self:end">
        <button type="submit">Применить</button>
        <button type="button" onclick="refreshNow()">Обновить</button>
      </div>
    </form>
  </div>

  <div class="grid">
    <div class="card" id="binance_card">
      <h2>Binance</h2>
      <div id="binance_status" class="ok" style="display:none">OK</div>
      <div id="binance_error" class="error" style="display:none"></div>
      <div class="rate" id="binance_avg">—</div>
      <div class="muted" id="binance_prices">—</div>
      <table>
        <thead><tr><th>#</th><th>Трейдер</th><th>Цена</th><th>Объём</th><th>Мин</th><th>Макс</th></tr></thead>
        <tbody id="binance_tbody"></tbody>
      </table>
    </div>

    <div class="card" id="bybit_card">
      <h2>Bybit</h2>
      <div id="bybit_status" class="ok" style="display:none">OK</div>
      <div id="bybit_error" class="error" style="display:none"></div>
      <div class="rate" id="bybit_avg">—</div>
      <div class="muted" id="bybit_prices">—</div>
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

  function fmt(n){ return Number(n).toLocaleString('ru-RU', {minimumFractionDigits:2, maximumFractionDigits:6}); }

  function paramsFromUI(){
    return {
      asset:   document.getElementById('asset').value,
      fiat:    document.getElementById('fiat').value,
      side:    document.getElementById('side').value,
      amount:  document.getElementById('amount').value,
      payment: document.getElementById('payment').value.trim(),
      // единый переключатель: merchant для Binance и verified для Bybit
      merchant: document.getElementById('verified').value,
      verified: document.getElementById('verified').value,
    };
  }

  async function load(){
    const p = paramsFromUI();
    const url = '/api/rates?' + new URLSearchParams(p).toString();
    const res = await fetch(url);
    let data = null;
    try { data = await res.json(); } catch(e){ data = {ok:false, errors:{fetch:'Bad JSON'}} }

    document.getElementById('ts').textContent = ' • обновлено: ' + new Date().toLocaleTimeString('ru-RU');

    // BINANCE
    const bErr = document.getElementById('binance_error');
    const bOk  = document.getElementById('binance_status');
    if (data.errors && data.errors.binance){
      bErr.style.display = ''; bErr.textContent = 'Ошибка: ' + data.errors.binance;
      bOk.style.display = 'none';
      document.getElementById('binance_avg').textContent = '—';
      document.getElementById('binance_prices').textContent = '—';
      document.getElementById('binance_tbody').innerHTML = '';
    } else if (data.binance){
      bErr.style.display = 'none';
      bOk.style.display = '';
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

    // BYBIT
    const yErr = document.getElementById('bybit_error');
    const yOk  = document.getElementById('bybit_status');
    if (data.errors && data.errors.bybit){
      yErr.style.display = ''; yErr.textContent = 'Ошибка: ' + data.errors.bybit;
      yOk.style.display = 'none';
      document.getElementById('bybit_avg').textContent = '—';
      document.getElementById('bybit_prices').textContent = '—';
      document.getElementById('bybit_tbody').innerHTML = '';
    } else if (data.bybit){
      yErr.style.display = 'none';
      yOk.style.display = '';
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

  function apply(ev){ ev.preventDefault(); refreshNow(); history.replaceState(null, '', '?' + new URLSearchParams(paramsFromUI()).toString()); }
  function refreshNow(){ load(); if (timer) clearInterval(timer); timer = setInterval(load, REFRESH_MS); }

  // Инициализация
  window.addEventListener('DOMContentLoaded', () => {
    // Параметры из URL -> в форму
    const q = new URLSearchParams(location.search);
    for (const id of ['asset','fiat','side','amount','payment','verified']){
      const v = q.get(id); if (v!==null) document.getElementById(id).value = v;
    }
    refreshNow();
  });
</script>
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
    # Откройте: http://127.0.0.1:5000/
    app.run(host="0.0.0.0", port=5000, debug=True)
