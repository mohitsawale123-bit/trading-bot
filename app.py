import requests, os, numpy as np, time
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

capital = 5
risk_percent = 0.02

trade_count = 0
last_trade_day = None
last_update_minute = None

total_trades = 0
wins = 0
losses = 0

prices = []

# === TELEGRAM ===
def send_msg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

def send_buttons(msg):
    try:
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ YES", "callback_data": "YES"},
                {"text": "❌ NO", "callback_data": "NO"}
            ]]
        }
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": msg, "reply_markup": keyboard})
    except:
        pass

# === SESSION FILTER ===
def session_active():
    hour = datetime.utcnow().hour
    return 7 <= hour <= 17

# === STABLE GOLD PRICE (PRIMARY + BACKUP) ===
def get_price():
    try:
        url = "https://api.gold-api.com/price/XAUUSD"
        data = requests.get(url, timeout=10).json()
        if data.get("price"):
            return float(data["price"])
    except:
        pass

    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
        data = requests.get(url, timeout=10).json()
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        return None

# === CANDLE ===
def build_candle():
    if len(prices) < 5:
        return None
    return {
        "open": prices[-5],
        "close": prices[-1],
        "high": max(prices[-5:]),
        "low": min(prices[-5:])
    }

def strong_bullish(c):
    return c and c["close"] > c["open"] and (c["close"] - c["open"]) > 0.5

def strong_bearish(c):
    return c and c["close"] < c["open"] and (c["open"] - c["close"]) > 0.5

# === TREND ===
def trend():
    if len(prices) < 50:
        return None
    return "UP" if np.mean(prices[-20:]) > np.mean(prices[-50:]) else "DOWN"

# === TREND STRENGTH ===
def trend_strength():
    if len(prices) < 20:
        return "UNKNOWN"
    move = abs(prices[-1] - prices[-10])
    if move > 3:
        return "STRONG"
    elif move > 1.5:
        return "MODERATE"
    else:
        return "WEAK"

# === STRUCTURE ===
def market_structure():
    if len(prices) < 20:
        return None
    if max(prices[-10:]) > max(prices[-20:-10]):
        return "BOS_UP"
    if min(prices[-10:]) < min(prices[-20:-10]):
        return "BOS_DOWN"

# === LEVELS ===
def levels():
    return max(prices[-30:]), min(prices[-30:])

# === LIQUIDITY ===
def liquidity_sweep(price, high, low):
    prev = prices[-2]
    if price > high and prev < high:
        return "SWEEP_BUY"
    if price < low and prev > low:
        return "SWEEP_SELL"

# === FIB ===
def fibonacci(high, low, price):
    fib50 = low + (high - low) * 0.5
    fib618 = low + (high - low) * 0.618
    return abs(price - fib50) < 0.5 or abs(price - fib618) < 0.5

# === LOT ===
def calc_lot(entry, sl):
    risk = capital * risk_percent
    dist = abs(entry - sl)
    return round(max(min(risk / (dist * 100), 0.02), 0.001), 3)

# === SMART STATUS ===
def smart_status(price, high, low, trend_dir, structure):
    strength = trend_strength()

    if abs(price - high) < 1:
        liquidity_zone = "Near High 🔺"
    elif abs(price - low) < 1:
        liquidity_zone = "Near Low 🔻"
    else:
        liquidity_zone = "Mid Range"

    if trend_dir == "UP":
        bias = "BUY ZONE"
    elif trend_dir == "DOWN":
        bias = "SELL ZONE"
    else:
        bias = "NO TRADE"

    return f"""
📊 MARKET STATUS (XAUUSD)

Trend: {trend_dir} ({strength})
Structure: {structure}
Liquidity: {liquidity_zone}
Bias: {bias}

📊 Trades: {total_trades}
⏳ Waiting for A+ setup
"""

# === START ===
send_msg("🚀 FINAL BOT ACTIVE (SMART MODE)")

# === LOOP ===
while True:
    try:
        now = datetime.utcnow()

        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        if not session_active():
            time.sleep(60)
            continue

        price = get_price()
        if price is None:
            time.sleep(60)
            continue

        prices.append(price)

        if len(prices) < 50:
            time.sleep(60)
            continue

        candle = build_candle()
        high, low = levels()

        trend_dir = trend()
        structure = market_structure()
        liq = liquidity_sweep(price, high, low)
        fib = fibonacci(high, low, price)

        signal = None

        if trend_dir == "UP" and liq == "SWEEP_SELL" and strong_bullish(candle):
            signal = "BUY"

        if trend_dir == "DOWN" and liq == "SWEEP_BUY" and strong_bearish(candle):
            signal = "SELL"

        score = 0
        if signal: score += 2
        if fib: score += 2
        if structure: score += 2
        if liq: score += 2

        if trade_count >= 2:
            time.sleep(60)
            continue

        # === TRADE SIGNAL (ANYTIME) ===
        if signal and score >= 8:
            entry = price
            sl = price - 2 if signal == "BUY" else price + 2
            tp = price + 6 if signal == "BUY" else price - 6

            total_trades += 1

            msg = f"""
🚨 PRO TRADE (XAUUSD)

Type: {signal}
Entry: {entry}
SL: {sl}
TP: {tp}

Score: {score}/10
"""
            send_buttons(msg)

            trade_count += 1
            prices = []

        # === SMART STATUS EVERY 30 MIN ===
        if now.minute in [0, 30] and last_update_minute != now.minute:
            last_update_minute = now.minute

            status_msg = smart_status(price, high, low, trend_dir, structure)
            send_msg(status_msg)

        time.sleep(60)

    except Exception as e:
        print(e)
        time.sleep(60)
