import requests, os, numpy as np, time, traceback
from datetime import datetime, timezone, timedelta

print("🔥 BTCUSD FINAL BOT (SMART UPDATE FIXED)")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

last_update_key = None
last_price = None

prices = []
candle_buffer = []

# ================= TELEGRAM =================
def send_msg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# ================= SAFE PRICE FETCH =================
def get_price():
    global last_price

    for _ in range(2):

        try:
            r = requests.get("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1", timeout=5)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    last_price = float(data[-1][4])
                    return last_price
        except: pass

        try:
            r = requests.get("https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=1&limit=1", timeout=5)
            data = r.json()
            if "result" in data and data["result"]["list"]:
                last_price = float(data["result"]["list"][0][4])
                return last_price
        except: pass

        try:
            r = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60", timeout=5)
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                last_price = float(data[0][4])
                return last_price
        except: pass

        try:
            r = requests.get("https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1", timeout=5)
            data = r.json()
            if "result" in data:
                pair = list(data["result"].keys())[0]
                last_price = float(data["result"][pair][-1][4])
                return last_price
        except: pass

        time.sleep(1)

    return last_price

# ================= STRATEGIES =================

def liquidity_grab(p):
    if len(p) < 30: return None, 0, "Liquidity Grab"
    h, l = max(p[-20:]), min(p[-20:])
    cur, prev = p[-1], p[-2]
    score = 0; signal = None

    if cur > h and prev < h:
        score += 20; signal = "SELL"
    elif cur < l and prev > l:
        score += 20; signal = "BUY"

    if abs(cur-prev) > 30: score += 20
    if max(p[-5:]) > max(p[-10:-5]): score += 20
    if abs(cur-np.mean(p[-5:])) < 20: score += 20
    if abs(p[-1]-p[-10]) > 50: score += 20

    return signal, score, "Liquidity Grab"


def breakout_retest(p):
    if len(p) < 30: return None, 0, "Breakout Retest"
    h, l = max(p[-20:]), min(p[-20:])
    cur, prev = p[-1], p[-2]
    score = 0; signal = None

    if cur > h: score += 20; signal = "BUY"
    elif cur < l: score += 20; signal = "SELL"

    if abs(cur-h) < 30 or abs(cur-l) < 30: score += 20
    if abs(cur-prev) > 25: score += 20
    if abs(p[-1]-p[-5]) > 40: score += 20
    if abs(p[-1]-p[-10]) > 60: score += 20

    return signal, score, "Breakout Retest"


def vwap_strategy(p):
    if len(p) < 20: return None, 0, "VWAP Bounce"
    vwap = np.mean(p[-20:])
    cur = p[-1]
    score = 0; signal = None

    if cur > vwap: signal = "BUY"; score += 20
    else: signal = "SELL"; score += 20

    if abs(cur-vwap) < 30: score += 20
    if abs(p[-1]-p[-5]) > 30: score += 20
    if abs(p[-1]-p[-10]) > 40: score += 20
    score += 20

    return signal, score, "VWAP Bounce"


def ema_strategy(p):
    if len(p) < 30: return None, 0, "EMA Pullback"
    ema9 = np.mean(p[-9:])
    ema21 = np.mean(p[-21:])
    cur = p[-1]

    score = 0; signal = None

    if ema9 > ema21:
        signal = "BUY"; score += 20
    else:
        signal = "SELL"; score += 20

    if abs(cur-ema9) < 30: score += 20
    if abs(p[-1]-p[-5]) > 30: score += 20
    if abs(p[-1]-p[-10]) > 40: score += 20
    score += 20

    return signal, score, "EMA Pullback"


def range_trap(p):
    if len(p) < 30: return None, 0, "Range Trap"
    h, l = max(p[-20:]), min(p[-20:])
    cur = p[-1]
    score = 0; signal = None

    if cur > h:
        signal = "SELL"; score += 20
    elif cur < l:
        signal = "BUY"; score += 20

    if abs(p[-1]-p[-5]) < 20: score += 20
    if abs(cur-h) < 30 or abs(cur-l) < 30: score += 20
    if abs(p[-1]-p[-10]) < 30: score += 20
    score += 20

    return signal, score, "Range Trap"

# ================= ENGINE =================
def strategy_engine(p):
    strategies = [
        liquidity_grab,
        breakout_retest,
        vwap_strategy,
        ema_strategy,
        range_trap
    ]

    best_signal, best_score, best_name = None, 0, None

    for strat in strategies:
        sig, sc, name = strat(p)
        if sc > best_score:
            best_signal, best_score, best_name = sig, sc, name

    return best_signal, best_score, best_name

# ================= START =================
send_msg("🚀 BTC BOT STARTED (SMART UPDATE FIXED)")

# ================= LOOP =================
while True:
    try:
        print("BOT LOOP RUNNING...")

        now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        price = get_price()

        if price is None:
            time.sleep(10)
            continue

        candle_buffer.append(price)

        if len(candle_buffer) < 5:
            time.sleep(60)
            continue

        candle_close = candle_buffer[-1]
        prices.append(candle_close)
        candle_buffer = []

        signal, score, strategy_name = strategy_engine(prices)

        # ===== SMART UPDATE FIX (NO MISS) =====
        current_slot = now.minute // 5
        slot_key = f"{now.hour}:{current_slot}"

        if last_update_key != slot_key:
            last_update_key = slot_key

            send_msg(f"""
📊 SMART UPDATE (BTCUSD)

Strategy: {strategy_name}
Score: {score}

Price: {round(price,2)}

⏳ Waiting for setup
""")

        # ===== TRADE =====
        if score >= 65 and signal:
            entry = price

            if signal == "BUY":
                sl = entry - 200
                tp1 = entry + 600
                tp2 = entry + 800
            else:
                sl = entry + 200
                tp1 = entry - 600
                tp2 = entry - 800

            send_msg(f"""
🚨 BTC TRADE SIGNAL

Strategy: {strategy_name}

Type: {signal}
Entry: {round(entry,2)}

SL: {round(sl,2)}
TP1: {round(tp1,2)}
TP2: {round(tp2,2)}

Score: {score}
RR: 1:3 🔥
""")

        time.sleep(60)

    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        time.sleep(60)
