import requests, os, numpy as np, time
from datetime import datetime

# === TELEGRAM CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# === ACCOUNT CONFIG ===
capital = 5
risk_percent = 0.02
trade_count = 0
last_trade_day = None
last_update_hour = None

# === TELEGRAM ===
def send_msg(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

def send_buttons(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ YES", "callback_data": "YES"},
                {"text": "❌ NO", "callback_data": "NO"}
            ]]
        }
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "reply_markup": keyboard})
    except:
        pass

# === PRICE (SAFE API) ===
def get_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        data = requests.get(url, timeout=10).json()
        return data.get("bitcoin", {}).get("usd", None)
    except:
        return None

# === NEWS FILTER ===
def is_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        data = requests.get(url, timeout=10).json()
        now = datetime.utcnow()

        for event in data:
            if event.get('impact') == 'High' and event.get('currency') == 'USD':
                event_time = datetime.strptime(event['date'], "%Y-%m-%dT%H:%M:%S")
                if abs((event_time - now).total_seconds()) <= 1800:
                    return True
    except:
        return False
    return False

# === PATTERN LOGIC ===
def triangle(prices):
    highs = prices[-20:]
    lows = prices[-20:]
    s1 = np.polyfit(range(len(highs)), highs, 1)[0]
    s2 = np.polyfit(range(len(lows)), lows, 1)[0]
    return s1 < 0 and s2 > 0

def retest(price, level):
    return abs(price - level) < 0.3

def calc_lot(entry, sl):
    risk = capital * risk_percent
    dist = abs(entry - sl)
    lot = risk / (dist * 100)
    return round(max(min(lot, 0.02), 0.001), 3)

# === START MESSAGE ===
send_msg("✅ Bot Started Successfully")

# === MAIN ENGINE ===
prices = []

while True:
    try:
        now = datetime.utcnow()

        # Reset daily trade count
        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        # === GET PRICE ===
        price = get_price()

        if price is None:
            send_msg("⚠️ Price fetch failed, retrying...")
            time.sleep(60)
            continue

        prices.append(price)

        if len(prices) < 50:
            time.sleep(60)
            continue

        high = max(prices[-30:])
        low = min(prices[-30:])

        signal = None
        if price > high:
            signal = "BUY"
        elif price < low:
            signal = "SELL"

        # === NEWS FILTER ===
        if is_news():
            send_msg("🚫 High Impact News - No Trade")
            time.sleep(300)
            continue

        # === TRADE LIMIT ===
        if trade_count >= 2:
            time.sleep(60)
            continue

        # === PATTERN CHECK ===
        tri = triangle(prices)
        ret = retest(price, high if signal == "BUY" else low)

        score = (3 if tri else 0) + (2 if ret else 0) + 2

        # === TRADE SIGNAL ===
        if signal and score >= 7:
            entry = price
            sl = price - 1 if signal == "BUY" else price + 1
            tp = price + 3 if signal == "BUY" else price - 3

            lot = calc_lot(entry, sl)

            msg = f"""
🚨 AUTO TRADE SIGNAL

Type: {signal}
Entry: {entry}
SL: {sl}
TP: {tp}

Lot: {lot}
Score: {score}/10
"""
            send_buttons(msg)

            trade_count += 1
            prices = []

        # === HOURLY UPDATE ===
        if last_update_hour != now.hour:
            last_update_hour = now.hour
            send_msg("⏳ No valid trade setup yet. Waiting for breakout...")

        time.sleep(60)

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
