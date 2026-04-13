import requests, os, numpy as np, time, traceback
from datetime import datetime, timedelta

print("🔥 FINAL BOT ACTIVE (IST + 3MIN STABLE)")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

trade_count = 0
last_trade_day = None
last_update_key = None

prices = []
candle_buffer = []

last_price = None

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

# === STABLE PRICE ===
def get_price():
    global last_price

    for _ in range(3):

        # Yahoo 1m
        try:
            res = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m",
                timeout=5
            )
            if res.status_code == 200:
                data = res.json()
                result = data.get("chart", {}).get("result")
                if result:
                    last_price = float(result[0]["meta"]["regularMarketPrice"])
                    return last_price
        except:
            pass

        # Yahoo normal
        try:
            res = requests.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/GC=F",
                timeout=5
            )
            if res.status_code == 200:
                data = res.json()
                result = data.get("chart", {}).get("result")
                if result:
                    last_price = float(result[0]["meta"]["regularMarketPrice"])
                    return last_price
        except:
            pass

        # Gold API
        try:
            res = requests.get(
                "https://api.gold-api.com/price/XAU",
                timeout=5
            )
            if res.status_code == 200:
                data = res.json()
                if "price" in data:
                    last_price = float(data["price"])
                    return last_price
        except:
            pass

        time.sleep(2)

    return last_price

# === TREND ===
def trend():
    if len(prices) < 50:
        return None
    return "UP" if np.mean(prices[-20:]) > np.mean(prices[-50:]) else "DOWN"

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

# === STATUS ===
def smart_status(price, high, low, trend_dir, structure):
    return f"""
📊 STATUS (XAUUSD)

Trend: {trend_dir}
Structure: {structure}

High: {round(high,2)}
Low: {round(low,2)}

Trades Today: {trade_count}
"""

# === START ===
send_msg("🚀 BOT STARTED (IST + 3MIN FINAL)")

# === LOOP ===
while True:
    try:
        # IST TIME FIX (NO ERROR)
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)

        print("Running at:", now)

        # reset daily trades
        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        price = get_price()

        if price is None:
            time.sleep(10)
            continue

        # === 5-MIN CANDLE ===
        candle_buffer.append(price)

        if len(candle_buffer) < 5:
            time.sleep(60)
            continue

        candle_close = candle_buffer[-1]
        prices.append(candle_close)
        candle_buffer = []

        if len(prices) < 50:
            time.sleep(60)
            continue

        high, low = levels()
        trend_dir = trend()
        structure = market_structure()

        signal = None

        if candle_close > high:
            signal = "BUY"
        elif candle_close < low:
            signal = "SELL"

        # === TRADE ===
        if signal:
            entry = candle_close
            sl = entry - 2 if signal == "BUY" else entry + 2
            tp = entry + 4 if signal == "BUY" else entry - 4

            msg = f"""
🚨 TRADE ALERT

Type: {signal}
Entry: {round(entry,2)}

SL: {round(sl,2)}
TP: {round(tp,2)}
"""
            send_buttons(msg)

            trade_count += 1
            prices = []

        # === EXACT 3-MIN UPDATE ===
        now_minute = now.minute

        if now_minute % 3 == 0:
            current_key = f"{now.hour}:{now_minute}"

            if last_update_key != current_key:
                last_update_key = current_key

                send_msg(smart_status(candle_close, high, low, trend_dir, structure))

        time.sleep(60)

    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        time.sleep(60)
