import requests, os, numpy as np, time, traceback
from datetime import datetime, timezone, timedelta

print("🔥 FINAL BOT ACTIVE (ULTIMATE FIXED VERSION)")

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

# === PRICE ===
def get_price():
    global last_price

    for _ in range(3):
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
    if len(prices) < 30:
        return None, None
    return max(prices[-30:]), min(prices[-30:])

# === STRUCTURE ===
def market_structure():
    if len(prices) < 20:
        return None
    if max(prices[-10:]) > max(prices[-20:-10]):
        return "BOS_UP"
    if min(prices[-10:]) < min(prices[-20:-10]):
        return "BOS_DOWN"

# === START ===
send_msg("🚀 BOT STARTED (ULTIMATE FIXED VERSION)")

# === LOOP ===
while True:
    try:
        now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        print("Running at:", now)

        # === RESET DAILY COUNT ===
        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        price = get_price()

        if price is None:
            time.sleep(10)
            continue

        # ================================
        # ✅ 3-MIN UPDATE (ALWAYS RUN)
        # ================================
        now_minute = now.minute

        if now_minute % 3 == 0:
            current_key = f"{now.hour}:{now_minute}"

            if last_update_key != current_key:
                last_update_key = current_key

                send_msg(f"""
📊 LIVE STATUS

Price: {round(price,2)}
Time: {now.strftime('%H:%M')}

Trades Today: {trade_count}
""")

        # ================================
        # 🔹 BUILD 5-MIN CANDLE
        # ================================
        candle_buffer.append(price)

        if len(candle_buffer) < 5:
            time.sleep(60)
            continue

        candle_close = candle_buffer[-1]
        prices.append(candle_close)
        candle_buffer = []

        # ================================
        # 🔹 STRATEGY
        # ================================
        if len(prices) < 50:
            time.sleep(60)
            continue

        high, low = levels()
        trend_dir = trend()
        structure = market_structure()

        signal = None

        if high and candle_close > high:
            signal = "BUY"
        elif low and candle_close < low:
            signal = "SELL"

        # ================================
        # 🚨 TRADE ALERT
        # ================================
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

        time.sleep(60)

    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        time.sleep(60)
