# ================= PURE 5M BTC BOT (FINAL) =================

import os
import time
import traceback
from datetime import datetime, timezone, timedelta

import numpy as np
import requests
import pandas as pd

print("🔥 BTC BOT (PURE 5M FINAL)")

MODE = "LIVE"
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IST_OFFSET = timedelta(hours=5, minutes=30)

candles_5m = []
last_update_key = None


# ---------------- TELEGRAM ----------------
def send_msg(msg):
    try:
        print("📤", msg)
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception as e:
        print("❌ Telegram Error:", e)


# ---------------- TIME ----------------
def now_ist():
    return datetime.now(timezone.utc) + IST_OFFSET


# ---------------- BINANCE DATA ----------------
def get_klines():
    import requests

    url = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    params = {
        "granularity": 300  # 5 min
    }

    res = requests.get(url, params=params, timeout=10)

    if res.status_code != 200:
        print("API ERROR:", res.text)
        return []

    data = res.json()

    candles = []
    for d in data:
        candles.append({
            "time": d[0],
            "low": float(d[1]),
            "high": float(d[2]),
            "open": float(d[3]),
            "close": float(d[4]),
        })

    candles.reverse()  # important

    return candles
    
    except Exception as e:
        print("❌ Request Failed:", e)
        return []
# ---------------- CSV (90 DAYS ROLLING) ----------------
def update_csv(candles):
    path = "btc_5m.csv"

    df_new = pd.DataFrame(candles)

    if os.path.exists(path):
        df_old = pd.read_csv(path)
        df = pd.concat([df_old, df_new])
    else:
        df = df_new

    df = df.drop_duplicates(subset=["time"])
    df = df.sort_values("time").tail(26000)

    df.to_csv(path, index=False)


# ---------------- HELPERS ----------------
def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def bullish(c): return c["close"] > c["open"]
def bearish(c): return c["close"] < c["open"]


def get_recent_high_low(n=10):
    highs = [c["high"] for c in candles_5m[-n:]]
    lows = [c["low"] for c in candles_5m[-n:]]
    return max(highs), min(lows)


# ---------------- MARKET TYPE ----------------
def identify_market_type():
    closes = [c["close"] for c in candles_5m]

    ema9 = ema(closes[-20:], 9)
    ema21 = ema(closes[-20:], 21)

    hi, lo = get_recent_high_low()
    last = closes[-1]

    if ema9 and ema21 and abs(ema9 - ema21) > 50:
        return "TRENDING", "UP" if ema9 > ema21 else "DOWN"

    if last > hi:
        return "BREAKOUT", "UP"
    if last < lo:
        return "BREAKOUT", "DOWN"

    return "MIXED", "WEAK"


# ================= 5 STRATEGIES =================

def liquidity_grab():
    c = candles_5m[-1]
    prev = candles_5m[-6:-1]

    hi = max(x["high"] for x in prev)
    lo = min(x["low"] for x in prev)

    if c["high"] > hi and c["close"] < hi:
        return "SELL", 70, "Liquidity Grab", c["high"] + 30

    if c["low"] < lo and c["close"] > lo:
        return "BUY", 70, "Liquidity Grab", c["low"] - 30

    return None, 0, "", None


def breakout_retest():
    hi, lo = get_recent_high_low()

    c = candles_5m[-1]
    p = candles_5m[-2]

    if p["close"] > hi and c["low"] <= hi and bullish(c):
        return "BUY", 75, "Breakout Retest", hi - 40

    if p["close"] < lo and c["high"] >= lo and bearish(c):
        return "SELL", 75, "Breakout Retest", lo + 40

    return None, 0, "", None


def vwap_bounce():
    closes = [c["close"] for c in candles_5m]
    vwap = np.mean(closes[-20:])

    c = candles_5m[-1]

    if abs(c["close"] - vwap) < 100:
        if bullish(c):
            return "BUY", 65, "VWAP Bounce", vwap - 50
        if bearish(c):
            return "SELL", 65, "VWAP Bounce", vwap + 50

    return None, 0, "", None


def ema_pullback():
    closes = [c["close"] for c in candles_5m]

    ema9 = ema(closes[-20:], 9)
    ema21 = ema(closes[-30:], 21)

    c = candles_5m[-1]

    if ema9 and ema21:
        if ema9 > ema21 and abs(c["low"] - ema9) < 80:
            return "BUY", 70, "EMA Pullback", ema21 - 50
        if ema9 < ema21 and abs(c["high"] - ema9) < 80:
            return "SELL", 70, "EMA Pullback", ema21 + 50

    return None, 0, "", None


def range_trap():
    hi, lo = get_recent_high_low()

    c = candles_5m[-1]

    if c["high"] > hi and bearish(c):
        return "SELL", 70, "Range Trap", c["high"] + 30

    if c["low"] < lo and bullish(c):
        return "BUY", 70, "Range Trap", c["low"] - 30

    return None, 0, "", None


# ---------------- STRATEGY ENGINE ----------------
def strategy_engine():
    strategies = [
        liquidity_grab,
        breakout_retest,
        vwap_bounce,
        ema_pullback,
        range_trap,
    ]

    best = {"signal": None, "score": 0, "sl": None, "name": ""}

    for s in strategies:
        sig, score, name, sl = s()
        if score > best["score"]:
            best = {"signal": sig, "score": score, "sl": sl, "name": name}

    return best


# ---------------- TRADE MESSAGE ----------------
def trade_signal_message(price, best, market_dir):
    risk = abs(price - best["sl"])
    tp = price + risk * 2 if best["signal"] == "BUY" else price - risk * 2

    return f"""🚨 BTC SIGNAL

Strategy: {best['name']}
Type: {best['signal']}
Entry: {price}

SL: {best['sl']}
TP: {tp}

Market Trend: {market_dir}
"""


# ---------------- SMART UPDATE ----------------
def smart_update_message(price, candle, market_type, market_dir, best):
    return f"""📊 BTC SMART UPDATE

Market: {market_type}
Trend: {market_dir}

Price: {price}

5M High: {candle['high']}
5M Low: {candle['low']}

Best Setup: {best['name']} ({best['score']})
"""


# ---------------- START ----------------
send_msg("🚀 BTC BOT STARTED (PURE 5M)")

while True:
    try:
        now = now_ist()

        candles_5m = get_klines()

        if not candles_5m:
            time.sleep(10)
            continue

        update_csv(candles_5m)

        price = candles_5m[-1]["close"]

        market_type, market_dir = identify_market_type()

        best = strategy_engine()

        can_trade = best["signal"] is not None and best["score"] >= 65

        # TRADE
        if MODE in ["LIVE", "HYBRID"] and can_trade:
            send_msg(trade_signal_message(price, best, market_dir))

        # SMART UPDATE
        if now.minute % 5 == 0:
            key = f"{now.hour}:{now.minute}"

            if last_update_key != key:
                last_update_key = key

                send_msg(
                    smart_update_message(
                        price,
                        candles_5m[-1],
                        market_type,
                        market_dir,
                        best
                    )
                )

        time.sleep(60)

    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()
        time.sleep(10)
