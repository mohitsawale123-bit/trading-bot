import requests, os, numpy as np, time
from datetime import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# === CONFIG ===
capital = 5
risk_percent = 0.02
trade_count = 0
last_trade_day = None
last_update_hour = None

# === TELEGRAM ===
def send_msg(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def send_buttons(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ YES", "callback_data": "YES"},
            {"text": "❌ NO", "callback_data": "NO"}
        ]]
    }
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "reply_markup": keyboard})

# === PRICE ===
def get_price():
    url = "https://api.metals.live/v1/spot/gold"
    data = requests.get(url).json()
    return float(data[0]["price"])

# === NEWS FILTER ===
def is_news():
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        data = requests.get(url).json()
        now = datetime.utcnow()

        for event in data:
            if event.get('impact') == 'High' and event.get('currency') == 'USD':
                event_time = datetime.strptime(event['date'], "%Y-%m-%dT%H:%M:%S")
                if abs((event_time - now).total_seconds()) <= 1800:
                    return True
    except:
        return False
    return False

# === PATTERN ===
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

# === MAIN ENGINE ===
prices = []
send_msg("✅ Bot Started Successfully")
while True:
    try:
        now = datetime.utcnow()

        # Reset daily trade count
        if last_trade_day != now.date():
            trade_count = 0
            last_trade_day = now.date()

        price = get_price()
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
            send_msg("🚫 News Event - No Trade")
            time.sleep(300)
            continue

        # === LIMIT ===
        if trade_count >= 2:
            time.sleep(60)
            continue

        tri = triangle(prices)
        ret = retest(price, high if signal == "BUY" else low)

        score = (3 if tri else 0) + (2 if ret else 0) + 2

        # === TRADE ===
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
            send_msg("⏳ No valid trade setup yet. Waiting for perfect breakout...")

        time.sleep(60)

    except Exception as e:
        print("Error:", e)
        time.sleep(60)
