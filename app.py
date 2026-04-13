import requests, os, numpy as np, time
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

capital = 5
risk_percent = 0.02

trade_count = 0
last_trade_day = None
last_update_key = None

prices = []

# === TELEGRAM ===
def send_msg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
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
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "reply_markup": keyboard}
        )
    except:
        pass

# === GOLD PRICE (PRIMARY + BACKUP) ===
def get_price():
    try:
        data = requests.get("https://api.gold-api.com/price/XAUUSD", timeout=10).json()
        if data.get("price"):
            return float(data["price"])
    except:
        pass

    try:
        data = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/GC=F",
            timeout=10
        ).json()
        return data["chart"]["result"][0]["meta"]["regularMarketPrice"]
    except:
        return None

# === TREND ===
def trend():
    if len(prices) < 50:
        return None
    return "UP" if np.mean(prices[-20:]) > np.mean(prices[-50:]) else "DOWN"

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

# === LEVELS ===
def levels():
    return max(prices[-30:]), min(prices[-30:])

# === STRUCTURE ===
def market_structure():
    if len(prices) < 20:
        return None
    if max(prices[-10:]) > max(prices[-20:-10]):
        return "BOS_UP"
    if min(prices[-10:]) < min(prices[-20:-10]):
        return "BOS_DOWN"

# === LIQUIDITY ===
def liquidity_sweep(price, high, low):
    if len(prices) < 2:
        return None
    prev = prices[-2]

    if price > high and prev < high:
        return "SWEEP_BUY"
    if price < low and prev > low:
        return "SWEEP_SELL"

# === VOLATILITY ===
def volatility():
    if len(prices) < 20:
        return "UNKNOWN"
    move = max(prices[-10:]) - min(prices[-10:])
    if move > 5:
        return "HIGH 🚀"
    elif move > 2:
        return "MEDIUM ⚡"
    else:
        return "LOW 💤"

# === SESSION ===
def market_session():
    hour = datetime.utcnow().hour
    if 7 <= hour < 12:
        return "London 🔵"
    elif 12 <= hour < 17:
        return "New York 🟣"
    elif 11 <= hour <= 13:
        return "Overlap 🔥"
    else:
        return "Asian 💤"

# === STATUS ===
def smart_status(price, high, low, trend_dir, structure):
    return f"""
📊 VIP MARKET STATUS (XAUUSD)

Session: {market_session()}
Volatility: {volatility()}

Trend: {trend_dir} ({trend_strength()})
Structure: {structure}

High: {round(high,2)}
Low: {round(low,2)}

Trades Today: {trade_count}

⏳ Waiting for A+ setup
"""

# === START ===
send_msg("🚀 BOT STARTED (FINAL FIXED VERSION)")

# === MAIN LOOP ===
while True:
    try:
        now = datetime.utcnow()

        # reset daily trades
        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        # === PRICE ===
        price = get_price()
        if price is None:
            time.sleep(60)
            continue

        prices.append(price)

        if len(prices) < 50:
            time.sleep(60)
            continue

        high, low = levels()
        trend_dir = trend()
        structure = market_structure()
        liq = liquidity_sweep(price, high, low)

        signal = None

        # === TRADE LOGIC ===
        if trend_dir == "UP" and liq == "SWEEP_SELL":
            signal = "BUY"

        if trend_dir == "DOWN" and liq == "SWEEP_BUY":
            signal = "SELL"

        # === TRADE EXECUTION ===
        if signal and volatility() != "LOW 💤":
            entry = price
            sl = price - 2 if signal == "BUY" else price + 2
            tp1 = price + 3 if signal == "BUY" else price - 3
            tp2 = price + 6 if signal == "BUY" else price - 6

            msg = f"""
🚨 VIP TRADE (XAUUSD)

Type: {signal}
Entry: {round(entry,2)}

SL: {round(sl,2)}
TP1: {round(tp1,2)}
TP2: {round(tp2,2)}

Trend: {trend_dir}
Volatility: {volatility()}

🎯 50% TP1, rest TP2
"""
            send_buttons(msg)

            trade_count += 1
            prices = []

        # === RELIABLE 15-MIN INTERVAL (NO MISS) ===
if last_update_key is None:
    last_update_key = int(time.time())

current_time = int(time.time())

# 900 sec = 15 minutes
if current_time - last_update_key >= 900:
    last_update_key = current_time

    send_msg(smart_status(price, high, low, trend_dir, structure))

        time.sleep(60)

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
