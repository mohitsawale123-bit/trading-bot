import requests, os, numpy as np, time, traceback
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

capital = 5
risk_percent = 0.02

trade_count = 0
last_trade_day = None
last_update_key = None

prices = []
candle_buffer = []

last_price = None
last_error_time = 0

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

# === FINAL STABLE PRICE ===
def get_price():
    global last_price, last_error_time

    # PRIMARY API
    try:
        res = requests.get("https://api.gold-api.com/price/XAUUSD", timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data and "price" in data:
                last_price = float(data["price"])
                return last_price
    except:
        pass

    # BACKUP API
    try:
        res = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/GC=F", timeout=10)
        if res.status_code == 200:
            data = res.json()
            result = data.get("chart", {}).get("result")
            if result:
                last_price = result[0]["meta"]["regularMarketPrice"]
                return last_price
    except:
        pass

    # FALLBACK (NO ERROR SPAM)
    if last_price:
        return last_price

    if time.time() - last_error_time > 300:
        print("⚠️ Price API temporarily unavailable")
        last_error_time = time.time()

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
    return "STRONG" if move > 3 else "MODERATE" if move > 1.5 else "WEAK"

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

# === STATUS ===
def smart_status(price, high, low, trend_dir, structure):
    return f"""
📊 VIP MARKET STATUS (XAUUSD)

Trend: {trend_dir} ({trend_strength()})
Structure: {structure}

High: {round(high,2)}
Low: {round(low,2)}

Volatility: {volatility()}
Trades Today: {trade_count}

⏳ Bot Running Smoothly
"""

# === START ===
send_msg("🚀 BOT STARTED (FINAL FIXED - NO API ERROR)")

# === LOOP ===
while True:
    try:
        now = datetime.now(timezone.utc)
        print("Running at:", now)

        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        price = get_price()
        if price is None:
            time.sleep(20)
            continue

        # === BUILD 5-MIN CANDLE ===
        candle_buffer.append(price)

        if len(candle_buffer) < 5:
            time.sleep(60)
            continue

        candle = {
            "open": candle_buffer[0],
            "close": candle_buffer[-1],
            "high": max(candle_buffer),
            "low": min(candle_buffer)
        }

        prices.append(candle["close"])
        candle_buffer = []

        if len(prices) < 50:
            time.sleep(60)
            continue

        high, low = levels()
        trend_dir = trend()
        structure = market_structure()
        liq = liquidity_sweep(candle["close"], high, low)

        signal = None

        if candle["close"] > high:
            signal = "BUY"
        elif candle["close"] < low:
            signal = "SELL"

        if liq == "SWEEP_SELL":
            signal = "BUY"
        elif liq == "SWEEP_BUY":
            signal = "SELL"

        score = 0

        if (trend_dir == "UP" and signal == "BUY") or (trend_dir == "DOWN" and signal == "SELL"):
            score += 2

        if liq:
            score += 2

        vol = volatility()
        if vol == "HIGH 🚀":
            score += 2
        elif vol == "MEDIUM ⚡":
            score += 1

        if structure:
            score += 2

        # === TRADE ===
        if signal and score >= 4:
            entry = candle["close"]
            sl = entry - 2 if signal == "BUY" else entry + 2
            tp1 = entry + 3 if signal == "BUY" else entry - 3
            tp2 = entry + 6 if signal == "BUY" else entry - 6

            msg = f"""
🚨 VIP TRADE (5M XAUUSD)

Type: {signal}
Entry: {round(entry,2)}

SL: {round(sl,2)}
TP1: {round(tp1,2)}
TP2: {round(tp2,2)}

Score: {score}/10
Trend: {trend_dir}
Volatility: {vol}

🎯 50% TP1, rest TP2
"""
            send_buttons(msg)

            trade_count += 1
            prices = []

        # === 15 MIN UPDATE ===
        if last_update_key is None:
            last_update_key = int(time.time())

        if int(time.time()) - last_update_key >= 900:
            last_update_key = int(time.time())
            send_msg(smart_status(candle["close"], high, low, trend_dir, structure))

        time.sleep(60)

    except Exception as e:
        print("CRASH ERROR:", e)
        traceback.print_exc()
        time.sleep(60)
