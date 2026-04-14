import os
import time
import math
import traceback
from datetime import datetime, timezone, timedelta

import numpy as np
import requests

print("🔥 BTCUSD FINAL BOT (STEP FLOW + 5 STRATEGIES)")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

IST_OFFSET = timedelta(hours=5, minutes=30)

last_update_key = None
last_price = None

prices = []

# 1-minute closes from APIs
one_min_closes = []

# built 5-minute candles
candles_5m = []  # each item: {"open","high","low","close","time"}

candle_buffer = []   # ✅ ADD THIS LINE

# ---------------- TELEGRAM ----------------
def send_msg(msg: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception:
        pass


# ---------------- TIME ----------------
def now_ist() -> datetime:
    return datetime.now(timezone.utc) + IST_OFFSET


# ---------------- PRICE FETCH (4 APIs + fallback) ----------------
def get_price() -> float | None:
    global last_price

    for _ in range(2):
        # Binance
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1",
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    last_price = float(data[-1][4])
                    return last_price
        except Exception:
            pass

        # Bybit
        try:
            r = requests.get(
                "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=1&limit=1",
                timeout=5,
            )
            data = r.json()
            if (
                isinstance(data, dict)
                and "result" in data
                and data["result"].get("list")
            ):
                last_price = float(data["result"]["list"][0][4])
                return last_price
        except Exception:
            pass

        # Coinbase
        try:
            r = requests.get(
                "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=60",
                timeout=5,
            )
            data = r.json()
            if isinstance(data, list) and data:
                last_price = float(data[0][4])
                return last_price
        except Exception:
            pass

        # Kraken
        try:
            r = requests.get(
                "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=1",
                timeout=5,
            )
            data = r.json()
            if isinstance(data, dict) and "result" in data:
                pair_keys = [k for k in data["result"].keys() if k != "last"]
                if pair_keys:
                    pair = pair_keys[0]
                    row = data["result"][pair][-1]
                    last_price = float(row[4])
                    return last_price
        except Exception:
            pass

        time.sleep(1)

    return last_price


# ---------------- HELPERS ----------------
def mean_safe(arr):
    return float(np.mean(arr)) if len(arr) > 0 else 0.0


def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def get_last_5m_candle():
    return candles_5m[-1] if candles_5m else None


def get_recent_high_low(n=12):
    if len(candles_5m) < n:
        return None, None
    highs = [c["high"] for c in candles_5m[-n:]]
    lows = [c["low"] for c in candles_5m[-n:]]
    return max(highs), min(lows)


def candle_body(c):
    return abs(c["close"] - c["open"])


def candle_range(c):
    return c["high"] - c["low"]


def upper_wick(c):
    return c["high"] - max(c["open"], c["close"])


def lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]


def bullish_candle(c):
    return c["close"] > c["open"]


def bearish_candle(c):
    return c["close"] < c["open"]


def strong_bullish(c):
    return bullish_candle(c) and candle_body(c) >= max(20, candle_range(c) * 0.45)


def strong_bearish(c):
    return bearish_candle(c) and candle_body(c) >= max(20, candle_range(c) * 0.45)


# ---------------- STEP 1: LIVE MARKET TYPE ----------------
def identify_market_type():
    if len(one_min_closes) < 30 or len(candles_5m) < 5:
        return "UNKNOWN", "WEAK"

    ema9_1m = ema(one_min_closes[-30:], 9)
    ema21_1m = ema(one_min_closes[-30:], 21)
    vwap_proxy = mean_safe(one_min_closes[-20:])
    recent_move = abs(one_min_closes[-1] - one_min_closes[-10])

    hi, lo = get_recent_high_low(8)
    last = one_min_closes[-1]

    if hi is None or lo is None or ema9_1m is None or ema21_1m is None:
        return "UNKNOWN", "WEAK"

    range_width = hi - lo

    # Trending → EMA / VWAP
    if abs(ema9_1m - ema21_1m) > 25 and abs(last - vwap_proxy) > 20 and recent_move > 60:
        direction = "UP" if ema9_1m > ema21_1m else "DOWN"
        return "TRENDING", direction

    # Sudden spike → Liquidity Grab
    if recent_move > 120:
        direction = "UP" if one_min_closes[-1] > one_min_closes[-5] else "DOWN"
        return "SUDDEN_SPIKE", direction

    # Sideways → Range Trap
    if range_width < 180 and recent_move < 45:
        return "SIDEWAYS", "WEAK"

    # Level break → Breakout
    if last > hi or last < lo:
        direction = "UP" if last > hi else "DOWN"
        return "LEVEL_BREAK", direction

    return "MIXED", "WEAK"


# ---------------- STEP 3 FILTERS ----------------
def session_active(now):
    # London + US focus in IST
    # London roughly 12:30–18:30 IST, US roughly 18:30–01:30 IST
    hour = now.hour
    minute = now.minute
    total = hour * 60 + minute

    london_start = 12 * 60 + 30
    london_end = 18 * 60 + 30
    us_start = 18 * 60 + 30
    us_end = 23 * 60 + 59

    return (london_start <= total <= london_end) or (us_start <= total <= us_end) or (0 <= total <= 90)


def avoid_event_trading(now):
    # Honest approximation only; not live economic calendar.
    # Blocks a few common high-risk windows around US data / roll times.
    total = now.hour * 60 + now.minute
    blocked = [
        (18 * 60 + 20, 18 * 60 + 50),
        (20 * 60 + 20, 20 * 60 + 50),
        (22 * 60 + 20, 22 * 60 + 50),
    ]
    return any(start <= total <= end for start, end in blocked)


def trade_action(score):
    if score >= 80:
        return "🔥 STRONG TRADE"
    if score >= 65:
        return "✅ GOOD"
    if score >= 50:
        return "⚠️ SKIP"
    return "❌ NO TRADE"


# ---------------- STRATEGY 1: LIQUIDITY GRAB ----------------
def liquidity_grab():
    name = "Liquidity Grab"
    if len(candles_5m) < 12:
        return None, 0, name, "No setup", None

    c = candles_5m[-1]
    prevs = candles_5m[-6:-1]
    prev_high = max(x["high"] for x in prevs)
    prev_low = min(x["low"] for x in prevs)

    score = 0
    signal = None
    setup = "Liquidity Sweep + Rejection"

    # 1) Sweep quality
    sweep_up = c["high"] > prev_high and c["close"] < prev_high
    sweep_down = c["low"] < prev_low and c["close"] > prev_low

    if sweep_up:
        signal = "SELL"
        wick = upper_wick(c)
        score += 20 if wick > 40 else 15 if wick > 25 else 10
    elif sweep_down:
        signal = "BUY"
        wick = lower_wick(c)
        score += 20 if wick > 40 else 15 if wick > 25 else 10
    else:
        return None, 0, name, "No sweep", None

    # 2) Rejection
    if signal == "BUY":
        score += 20 if strong_bullish(c) else 10 if bullish_candle(c) else 5
    else:
        score += 20 if strong_bearish(c) else 10 if bearish_candle(c) else 5

    # 3) BOS strength
    closes = [x["close"] for x in candles_5m[-6:]]
    if signal == "BUY":
        score += 20 if closes[-1] > max(closes[:-1]) else 10
    else:
        score += 20 if closes[-1] < min(closes[:-1]) else 10

    # 4) Pullback quality (approx using close near midpoint after sweep)
    midpoint = (c["high"] + c["low"]) / 2
    score += 20 if abs(c["close"] - midpoint) < 20 else 10

    # 5) Context
    mtype, mdir = identify_market_type()
    if mtype in ["SUDDEN_SPIKE", "TRENDING"]:
        score += 20
    elif mtype == "MIXED":
        score += 10
    else:
        score += 5

    sl = c["low"] - 30 if signal == "BUY" else c["high"] + 30
    return signal, min(score, 100), name, setup, sl


# ---------------- STRATEGY 2: BREAKOUT + RETEST ----------------
def breakout_retest():
    name = "Breakout + Retest"
    if len(candles_5m) < 15:
        return None, 0, name, "No setup", None

    level_high, level_low = get_recent_high_low(10)
    c = candles_5m[-1]
    p = candles_5m[-2]

    score = 0
    signal = None
    setup = "Breakout + Retest + Confirmation"

    if level_high is None or level_low is None:
        return None, 0, name, "No level", None

    # breakout candle previous, retest current
    broke_up = p["close"] > level_high
    broke_down = p["close"] < level_low

    if broke_up and c["low"] <= level_high and bullish_candle(c):
        signal = "BUY"
    elif broke_down and c["high"] >= level_low and bearish_candle(c):
        signal = "SELL"
    else:
        return None, 0, name, "Missing retest", None

    # level strength
    score += 20

    # breakout strength
    score += 20 if candle_body(p) > 35 else 10

    # retest quality
    score += 20 if abs(c["close"] - (level_high if signal == "BUY" else level_low)) < 40 else 10

    # rejection strength
    if signal == "BUY":
        score += 20 if strong_bullish(c) else 10
    else:
        score += 20 if strong_bearish(c) else 10

    # context
    mtype, _ = identify_market_type()
    score += 20 if mtype in ["TRENDING", "LEVEL_BREAK"] else 10 if mtype == "MIXED" else 5

    sl = (level_high - 40) if signal == "BUY" else (level_low + 40)
    return signal, min(score, 100), name, setup, sl


# ---------------- STRATEGY 3: VWAP BOUNCE ----------------
def vwap_bounce():
    name = "VWAP Bounce"
    if len(one_min_closes) < 25 or len(candles_5m) < 2:
        return None, 0, name, "No setup", None

    vwap = mean_safe(one_min_closes[-20:])
    c = candles_5m[-1]
    score = 0
    signal = None
    setup = "VWAP Bounce + Confirmation"

    if abs(c["close"] - vwap) > 120:
        return None, 0, name, "Too far from VWAP", None

    if c["close"] > vwap and c["low"] <= vwap and bullish_candle(c):
        signal = "BUY"
    elif c["close"] < vwap and c["high"] >= vwap and bearish_candle(c):
        signal = "SELL"
    else:
        return None, 0, name, "No clean bounce", None

    # vwap trend
    score += 20 if abs(one_min_closes[-1] - vwap) > 15 else 10

    # pullback distance
    score += 20 if abs(c["close"] - vwap) < 40 else 10

    # rejection
    if signal == "BUY":
        score += 20 if strong_bullish(c) else 10
    else:
        score += 20 if strong_bearish(c) else 10

    # momentum
    score += 20 if abs(one_min_closes[-1] - one_min_closes[-5]) > 60 else 10

    # session context
    score += 20 if session_active(now_ist()) else 5

    sl = vwap - 50 if signal == "BUY" else vwap + 50
    return signal, min(score, 100), name, setup, sl


# ---------------- STRATEGY 4: EMA TREND PULLBACK ----------------
def ema_pullback():
    name = "EMA Pullback"
    if len(one_min_closes) < 30 or len(candles_5m) < 2:
        return None, 0, name, "No setup", None

    ema9 = ema(one_min_closes[-20:], 9)
    ema21 = ema(one_min_closes[-30:], 21)
    c = candles_5m[-1]
    score = 0
    signal = None
    setup = "EMA Pullback + Rejection"

    if ema9 is None or ema21 is None:
        return None, 0, name, "EMA unavailable", None

    if ema9 > ema21 and abs(c["low"] - ema9) < 80 and bullish_candle(c):
        signal = "BUY"
    elif ema9 < ema21 and abs(c["high"] - ema9) < 80 and bearish_candle(c):
        signal = "SELL"
    else:
        return None, 0, name, "No EMA pullback", None

    # trend strength
    score += 20 if abs(ema9 - ema21) > 40 else 10

    # alignment
    score += 20

    # pullback clarity
    score += 20 if abs(c["close"] - ema9) < 40 else 10

    # rejection
    if signal == "BUY":
        score += 20 if strong_bullish(c) else 10
    else:
        score += 20 if strong_bearish(c) else 10

    # momentum
    score += 20 if abs(one_min_closes[-1] - one_min_closes[-5]) > 50 else 10

    sl = ema21 - 60 if signal == "BUY" else ema21 + 60
    return signal, min(score, 100), name, setup, sl


# ---------------- STRATEGY 5: RANGE LIQUIDITY TRAP ----------------
def range_trap():
    name = "Range Trap"
    if len(candles_5m) < 12:
        return None, 0, name, "No setup", None

    recent = candles_5m[-10:]
    high = max(c["high"] for c in recent)
    low = min(c["low"] for c in recent)
    width = high - low

    c = candles_5m[-1]
    score = 0
    signal = None
    setup = "Range Trap + Reversal"

    # strong trend skip
    mtype, _ = identify_market_type()
    if mtype == "TRENDING":
        return None, 0, name, "Strong trend skip", None

    if width > 250:
        return None, 0, name, "Range not clean", None

    fake_break_high = c["high"] > high and c["close"] < high
    fake_break_low = c["low"] < low and c["close"] > low

    if fake_break_low and bullish_candle(c):
        signal = "BUY"
    elif fake_break_high and bearish_candle(c):
        signal = "SELL"
    else:
        return None, 0, name, "No fake breakout", None

    # range clarity
    score += 20

    # fake breakout strength
    score += 20 if candle_range(c) > 80 else 10

    # rejection
    if signal == "BUY":
        score += 20 if lower_wick(c) > candle_body(c) else 10
    else:
        score += 20 if upper_wick(c) > candle_body(c) else 10

    # return inside range
    score += 20

    # context
    score += 20 if mtype == "SIDEWAYS" else 10

    sl = c["low"] - 30 if signal == "BUY" else c["high"] + 30
    return signal, min(score, 100), name, setup, sl


# ---------------- STEP 2: SCAN STRATEGIES IN PRIORITY ORDER ----------------
def strategy_engine():
    strategies = [
        liquidity_grab,
        breakout_retest,
        vwap_bounce,
        ema_pullback,
        range_trap,
    ]

    best = {
        "signal": None,
        "score": 0,
        "strategy": "No strategy building",
        "setup": "No strategy building",
        "sl": None,
    }

    for strat in strategies:
        signal, score, name, setup, sl = strat()
        if score > best["score"]:
            best = {
                "signal": signal,
                "score": score,
                "strategy": name,
                "setup": setup,
                "sl": sl,
            }

    return best


# ---------------- STEP 3: APPLY FILTERS ----------------
def passes_trade_filter(best, price):
    now = now_ist()

    if best["signal"] is None:
        return False, "No signal"

    if best["score"] < 65:
        return False, "Score too low"

    if not session_active(now):
        return False, "Session inactive"

    if avoid_event_trading(now):
        return False, "Avoid event window"

    if best["sl"] is None:
        return False, "No clear SL"

    risk = abs(price - best["sl"])
    if risk <= 0:
        return False, "Invalid risk"

    tp1 = price + risk * 3 if best["signal"] == "BUY" else price - risk * 3
    rr = abs(tp1 - price) / risk
    if rr < 3:
        return False, "RR below 1:3"

    # confirmation candle
    c = get_last_5m_candle()
    if c is None:
        return False, "No confirmation candle"

    if best["signal"] == "BUY" and not bullish_candle(c):
        return False, "No bullish confirmation"
    if best["signal"] == "SELL" and not bearish_candle(c):
        return False, "No bearish confirmation"

    return True, "PASS"


# ---------------- SMART UPDATE FORMAT ----------------
def smart_update_message(price, last_candle, market_type, market_dir, best):
    high = last_candle["high"] if last_candle else price
    low = last_candle["low"] if last_candle else price
    score = best["score"]
    strategy = best["strategy"]

    if score >= 40:
        trend_text = f"{market_dir} (Strong)" if market_dir in ["UP", "DOWN"] else "UP / Down (Strong)"
        bias = "BUY ZONE" if market_dir == "UP" else "SELL ZONE" if market_dir == "DOWN" else "BUY ZONE"
        win = "Approx - 40-50% 🔥"
        market_name = "Strong market"
    else:
        trend_text = "Weak"
        bias = "weak zone"
        win = "Approx - 0-40% 🔥"
        market_name = "Weak / Avoid Market"

    return f"""📊 BTC SMART UPDATE

Market: {market_name}
Trend: {trend_text}

Current Price: {price}

Last 5 min candle - High price: {high}
Last 5 min candle - Low price: {low}

Bias: {bias}
Strategy setup: {strategy}
Win Rate: {win}

⏳ Waiting for trade signal setup"""


# ---------------- TRADE SIGNAL FORMAT ----------------
def trade_signal_message(price, best, market_dir):
    score = best["score"]
    signal = best["signal"]
    setup = best["setup"]
    sl = best["sl"]

    action = trade_action(score)
    risk = abs(price - sl)
    tp1 = price + risk * 3 if signal == "BUY" else price - risk * 3
    tp2 = price + risk * 4 if signal == "BUY" else price - risk * 4

    trend_text = "STRONG" if market_dir in ["UP", "DOWN"] else "STRONG"

    return f"""🚨 BTC TRADE SIGNAL

Type: {"BUY 📈" if signal == "BUY" else "Sell 📉"}
Entry: {price}

SL: {sl}
TP1: {tp1}
TP2: {tp2 if score > 85 else "Only if score > 85"}

RR: 1:3 🔥

📊 Market Context:
Trend: {trend_text}
Setup: {setup}
Score: {score}
Action: {action}

📈Win Probability on TP1 Hit: 70% ✅
📈Win Probability on TP2 Hit: 45% 🎯"""


# ---------------- START ----------------
send_msg("🚀 BTC BOT STARTED (FINAL STEP FLOW VERSION)")

# ---------------- LOOP ----------------
while True:
    try:
        global candle_buffer, last_update_key   # ✅ ADD THIS LINE

        now = now_ist()
        price = get_price()
        print(f"✅ Loop running | Time: {now.strftime('%H:%M:%S')} | Price: {price}")

        if price is None:
            time.sleep(10)
            continue

        # store 1m price
        one_min_closes.append(price)
        if len(one_min_closes) > 500:
            one_min_closes = one_min_closes[-500:]

        # build 5m candle manually
        candle_buffer.append(price)
        if len(candle_buffer) >= 5:
            o = candle_buffer[0]
            h = max(candle_buffer)
            l = min(candle_buffer)
            c = candle_buffer[-1]
            candles_5m.append({
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "time": now.strftime("%H:%M"),
            })
            candle_buffer = []
            if len(candles_5m) > 300:
                candles_5m = candles_5m[-300:]

        # Step 1
        market_type, market_dir = identify_market_type()

        # Step 2
        best = strategy_engine()

        # Step 3
        can_trade, _reason = passes_trade_filter(best, price)

        # exact 5 min smart update using your logic
        now_minute = now.minute
        if now_minute % 5 == 0:
            current_key = f"{now.hour}:{now_minute}"
            if last_update_key != current_key:
                last_update_key = current_key
                last_candle = get_last_5m_candle()
                if can_trade:
                    send_msg(trade_signal_message(price, best, market_dir))
                else:
                    send_msg(smart_update_message(price, last_candle, market_type, market_dir, best))

        # anytime trade if strong/good and filter passes
        if can_trade and best["score"] >= 50:
            send_msg(trade_signal_message(price, best, market_dir))
            time.sleep(60)

        time.sleep(60)

    except Exception as e:
    print("ERROR:", e)
    traceback.print_exc()
    time.sleep(10)
    continue   # ✅ ADD THIS LINE
