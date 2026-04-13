import requests, os, numpy as np, time
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

capital = 5
risk_percent = 0.02

trade_count = 0
last_trade_day = None
last_update_hour = None

# === PERFORMANCE TRACKING ===
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
    return 7 <= hour <= 17  # London + NY overlap

# === PRICE ===
def get_price():
    try:
        url = "https://api.metals.live/v1/spot/gold"
        return requests.get(url).json()[0]["price"]
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

# === RETEST ===
def retest(price, level):
    return abs(price - level) < 0.5

# === LOT ===
def calc_lot(entry, sl):
    risk = capital * risk_percent
    dist = abs(entry - sl)
    return round(max(min(risk / (dist * 100), 0.02), 0.001), 3)

# === PERFORMANCE REPORT ===
def report():
    if total_trades == 0:
        return "No trades yet"
    winrate = round((wins / total_trades) * 100, 2)
    return f"Trades: {total_trades} | Wins: {wins} | Loss: {losses} | WR: {winrate}%"

send_msg("🚀 PRODUCTION BOT ACTIVE")
send_msg("📊 Session + Accuracy Tracking Enabled")

while True:
    try:
        now = datetime.utcnow()

        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        # === SESSION CHECK ===
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

        tr = trend()
        structure = market_structure()
        liq = liquidity_sweep(price, high, low)
        fib = fibonacci(high, low, price)

        signal = None

        if tr == "UP" and liq == "SWEEP_SELL" and strong_bullish(candle):
            signal = "BUY"

        if tr == "DOWN" and liq == "SWEEP_BUY" and strong_bearish(candle):
            signal = "SELL"

        # === SCORE ===
        score = 0
        if signal:
            score += 2
        if fib:
            score += 2
        if structure:
            score += 2
        if liq:
            score += 2

        # === LIMIT ===
        if trade_count >= 2:
            time.sleep(60)
            continue

        # === EXECUTION ===
        if signal and score >= 8:
            entry = price
            sl = price - 2 if signal == "BUY" else price + 2
            tp = price + 6 if signal == "BUY" else price - 6
            lot = calc_lot(entry, sl)

            total_trades += 1

            msg = f"""
🚨 PRO TRADE (XAUUSD)

Type: {signal}
Entry: {entry}
SL: {sl}
TP: {tp}

Score: {score}/10

📊 {report()}
"""
            send_buttons(msg)

            trade_count += 1
            prices = []

        # === HOURLY STATUS ===
        if last_update_hour != now.hour:
            last_update_hour = now.hour
            send_msg(f"📊 Status Update\n{report()}")

        time.sleep(60)

    except Exception as e:
        print(e)
        time.sleep(60)
