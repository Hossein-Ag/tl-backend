"""
TL Tracker Backend — Railway Server
=====================================
قیمت رو از tldb.info می‌خونه و به سایت github.io می‌ده
"""

from flask import Flask, jsonify
from flask_cors import CORS
import requests
import json
import time
import threading
from datetime import datetime

app = Flask(__name__)
CORS(app)  # اجازه میده سایت github.io از این سرور بخونه

# ─── تنظیمات ────────────────────────────────────────────────
PRICE_API = "https://tldb.info/api/ah/prices"
CACHE_TTL = 30  # هر ۳۰ ثانیه قیمت رو آپدیت کنه

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://tldb.info/",
}

# ─── Cache ───────────────────────────────────────────────────
cache = {
    "data": None,
    "last_update": 0,
    "raw": None,
}

price_log = {}  # item_id -> [(timestamp, price), ...]


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
