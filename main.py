from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import json
import time
import threading
from datetime import datetime
import random

app = Flask(__name__)
CORS(app)

PRICE_API = "https://tldb.info/api/ah/prices"
CACHE_TTL = 30

# User-Agent Ù‡Ø§ÛŒ Ù…Ø®ØªÙ„Ù Ø¨Ø±Ø§ÛŒ Ø´Ø¨ÛŒÙ‡â€ŒØ³Ø§Ø²ÛŒ Ù…Ø±ÙˆØ±Ú¯Ø±
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]

cache = {"data": None, "last_update": 0}
price_log = {}

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://tldb.info",
        "Referer": "https://tldb.info/auction-house",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
    }

def fetch_from_tldb():
    session = requests.Session()
    try:
        # Ø§ÙˆÙ„ ØµÙØ­Ù‡ Ø§ØµÙ„ÛŒ Ø±Ùˆ Ø¨Ø§Ø² Ú©Ù† ØªØ§ cookie Ø¨Ú¯ÛŒØ±ÛŒÙ…
        session.get("https://tldb.info/auction-house", headers=get_headers(), timeout=10)
        time.sleep(0.5)
        # Ø¨Ø¹Ø¯ API Ø±Ùˆ Ø¨Ø²Ù†
        resp = session.get(PRICE_API, headers=get_headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[{now()}] Ø®Ø·Ø§: {e}")
        return None

def decompress_cj(data):
    if not data:
        return []
    if isinstance(data, list) and len(data) > 1:
        first = data[0]
        if isinstance(first, list) and first and isinstance(first[0], str):
            keys = first
            result = []
            for row in data[1:]:
                if isinstance(row, list):
                    obj = {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
                    result.append(obj)
            return result
        if isinstance(first, dict):
            return data
    return data if isinstance(data, list) else []

def parse_prices(raw):
    if not raw:
        return {}
    result = {}
    for server, val in raw.get("list", {}).items():
        try:
            if isinstance(val, str):
                val = json.loads(val)
            rows = decompress_cj(val)
            if rows:
                result[server] = rows
        except:
            continue
    for region, items in raw.get("regions", {}).items():
        if isinstance(items, list):
            result[region] = items
    return result

def find_price(prices_map, item_id, region="eu"):
    hits = []
    for server, rows in prices_map.items():
        if not server.startswith(region):
            continue
        for row in (rows or []):
            if not row:
                continue
            if isinstance(row, dict):
                rid = row.get("id") or row.get("item_id") or row.get("i")
                p   = row.get("price") or row.get("min_price") or row.get("p")
                qty = row.get("quantity") or row.get("qty") or 0
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                rid, p = row[0], row[1]
                qty = row[2] if len(row) > 2 else 0
            else:
                continue
            if str(rid) == str(item_id) and p and int(p) > 0:
                hits.append({"server": server, "price": int(p), "qty": int(qty or 0)})
    return hits

def log_price(item_id, price):
    if item_id not in price_log:
        price_log[item_id] = []
    price_log[item_id].append((time.time(), price))
    cutoff = time.time() - 7 * 86400
    price_log[item_id] = [(t, p) for t, p in price_log[item_id] if t >= cutoff]

def calc_avg(item_id):
    log = price_log.get(item_id, [])
    if not log:
        return None
    cutoff = time.time() - 7 * 86400
    recent = [p for t, p in log if t >= cutoff]
    return round(sum(recent) / len(recent)) if recent else None

def now():
    return datetime.now().strftime("%H:%M:%S")

def refresh_cache():
    raw = fetch_from_tldb()
    if raw:
        cache["data"] = parse_prices(raw)
        cache["last_update"] = time.time()
        print(f"[{now()}] âœ… Cache: {len(cache['data'])} Ø³Ø±ÙˆØ±")
    else:
        print(f"[{now()}] âŒ Cache Ø¢Ù¾Ø¯ÛŒØª Ù†Ø´Ø¯")

def get_cached():
    if time.time() - cache["last_update"] > CACHE_TTL or not cache["data"]:
        refresh_cache()
    return cache["data"]

def bg_refresh():
    while True:
        try:
            refresh_cache()
        except Exception as e:
            print(f"[{now()}] bg Ø®Ø·Ø§: {e}")
        time.sleep(CACHE_TTL)

@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "TL Tracker API"})

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "last_update": cache["last_update"],
        "servers_cached": len(cache["data"] or {}),
        "items_tracked": len(price_log),
        "time": now(),
    })

@app.route("/price/<item_id>")
def get_price(item_id):
    region = request.args.get("region", "eu")
    prices_map = get_cached()

    if not prices_map:
        return jsonify({"error": "tldb.info Ø¯Ø± Ø¯Ø³ØªØ±Ø³ Ù†ÛŒØ³Øª", "price": None}), 503

    hits = find_price(prices_map, item_id, region)

    if not hits:
        return jsonify({
            "item_id": item_id, "region": region,
            "price": None, "avg_7d": None, "entries": [],
            "message": "Ø¢ÛŒØªÙ… Ø¯Ø± Ø¨Ø§Ø²Ø§Ø± ÛŒØ§ÙØª Ù†Ø´Ø¯",
        })

    min_price = min(h["price"] for h in hits)
    log_price(item_id, min_price)
    avg = calc_avg(item_id)
    diff = round(((min_price - avg) / avg) * 100, 1) if avg else None

    return jsonify({
        "item_id": item_id,
        "region": region,
        "price": min_price,
        "avg_7d": avg,
        "diff_pct": diff,
        "signal": "buy" if (avg and min_price < avg) else "hold",
        "entries": hits,
        "timestamp": now(),
        "data_points": len(price_log.get(item_id, [])),
    })

if __name__ == "__main__":
    import os
    print(f"[{now()}] Ø³Ø±ÙˆØ± Ø´Ø±ÙˆØ¹ Ø´Ø¯...")
    refresh_cache()
    threading.Thread(target=bg_refresh, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
def fetch_from_tldb():
    """مستقیم از tldb.info قیمت می‌گیره"""
    try:
        resp = requests.get(PRICE_API, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[{now()}] خطا در دریافت: {e}")
        return None


def decompress_cj(data):
    """compress-json رو decode می‌کنه"""
    if not data:
        return []

    # فرمت ۱: [[keys...], [vals...], ...]
    if isinstance(data, list) and len(data) > 1:
        first = data[0]
        if isinstance(first, list) and len(first) > 0 and isinstance(first[0], str):
            keys = first
            result = []
            for row in data[1:]:
                if isinstance(row, list):
                    obj = {}
                    for i, k in enumerate(keys):
                        if i < len(row):
                            obj[k] = row[i]
                    result.append(obj)
            return result

    # فرمت ۲: لیست آبجکت‌ها
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        return data

    return data if isinstance(data, list) else []


def parse_prices(raw_data):
    """قیمت‌ها رو parse می‌کنه و برمی‌گردونه"""
    if not raw_data:
        return {}

    result = {}
    raw_list = raw_data.get("list", {})

    for server, raw in raw_list.items():
        try:
            if isinstance(raw, str):
                raw = json.loads(raw)
            rows = decompress_cj(raw)
            if rows:
                result[server] = rows
        except Exception:
            continue

    return result


def find_price(prices_map, item_id, region="eu"):
    """قیمت یه آیتم خاص رو پیدا می‌کنه"""
    hits = []

    for server, rows in prices_map.items():
        if not server.startswith(region):
            continue
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not row:
                continue

            item_row_id = None
            price = None
            qty = 0

            if isinstance(row, dict):
                item_row_id = row.get("id") or row.get("item_id") or row.get("i")
                price = row.get("price") or row.get("min_price") or row.get("p")
                qty = row.get("quantity") or row.get("qty") or row.get("q") or 0
            elif isinstance(row, (list, tuple)) and len(row) >= 2:
                item_row_id, price = row[0], row[1]
                qty = row[2] if len(row) > 2 else 0

            if str(item_row_id) == str(item_id) and price and int(price) > 0:
                hits.append({
                    "server": server,
                    "price": int(price),
                    "qty": int(qty or 0),
                })

    return hits


def log_price(item_id, price):
    """قیمت رو ذخیره می‌کنه"""
    if item_id not in price_log:
        price_log[item_id] = []

    price_log[item_id].append((time.time(), price))

    # فقط ۷ روز نگه داره
    week = 7 * 24 * 3600
    cutoff = time.time() - week
    price_log[item_id] = [(t, p) for t, p in price_log[item_id] if t >= cutoff]


def calc_avg(item_id, days=7):
    """میانگین ۷ روزه رو حساب می‌کنه"""
    if item_id not in price_log or not price_log[item_id]:
        return None

    cutoff = time.time() - days * 86400
    recent = [p for t, p in price_log[item_id] if t >= cutoff]

    if not recent:
        return None

    return round(sum(recent) / len(recent))


def now():
    return datetime.now().strftime("%H:%M:%S")


def refresh_cache():
    """Cache رو آپدیت می‌کنه"""
    raw = fetch_from_tldb()
    if raw:
        cache["raw"] = raw
        cache["data"] = parse_prices(raw)
        cache["last_update"] = time.time()
        print(f"[{now()}] Cache آپدیت شد — {len(cache['data'])} سرور")
    return cache["data"]


def get_cached():
    """Cache رو می‌گیره، اگه قدیمیه آپدیت می‌کنه"""
    if time.time() - cache["last_update"] > CACHE_TTL or cache["data"] is None:
        refresh_cache()
    return cache["data"]


# ─── Background refresh ───────────────────────────────────────
def background_refresh():
    while True:
        try:
            refresh_cache()
        except Exception as e:
            print(f"[{now()}] خطا در background refresh: {e}")
        time.sleep(CACHE_TTL)


# ─── Routes ──────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "message": "TL Tracker API",
        "endpoints": {
            "/price/<item_id>": "قیمت یه آیتم (region=eu/us/jp)",
            "/price/<item_id>?region=eu": "با فیلتر region",
            "/health": "وضعیت سرور",
        }
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "last_update": cache["last_update"],
        "servers_cached": len(cache["data"] or {}),
        "items_tracked": len(price_log),
        "time": now(),
    })


@app.route("/price/<item_id>")
def get_price(item_id):
    from flask import request
    region = request.args.get("region", "eu")

    prices_map = get_cached()

    if not prices_map:
        return jsonify({"error": "سرور tldb.info در دسترس نیست", "price": None}), 503

    hits = find_price(prices_map, item_id, region)

    if not hits:
        return jsonify({
            "item_id": item_id,
            "region": region,
            "price": None,
            "avg_7d": None,
            "entries": [],
            "message": "آیتم در بازار یافت نشد",
        })

    min_price = min(h["price"] for h in hits)

    # ذخیره در لاگ
    log_price(item_id, min_price)
    avg = calc_avg(item_id)

    # محاسبه diff
    diff_pct = round(((min_price - avg) / avg) * 100, 1) if avg else None

    return jsonify({
        "item_id": item_id,
        "region": region,
        "price": min_price,
        "avg_7d": avg,
        "diff_pct": diff_pct,
        "signal": "buy" if (avg and min_price < avg) else "hold",
        "entries": hits,
        "timestamp": now(),
        "data_points": len(price_log.get(item_id, [])),
    })


# ─── Start ───────────────────────────────────────────────────
if __name__ == "__main__":
    import os

    # اول cache رو پر کن
    print(f"[{now()}] سرور شروع به کار کرد...")
    refresh_cache()

    # background refresh
    t = threading.Thread(target=background_refresh, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
