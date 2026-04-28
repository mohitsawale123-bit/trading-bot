# ============================================================
#  BTC BOT — FULL UPGRADED (Session + Event + Multi-TF + CSV)
#  Requirements: 10-Step Flow | 5 Strategies | 90-Day Rolling
#  Tested base: Coinbase public API (no auth needed)
# ============================================================

import os
import time
import traceback
from datetime import datetime, timezone, timedelta

import numpy as np
import requests
import pandas as pd

print("🔥 BTC BOT — UPGRADED (Session + Event + Multi-TF)")

# ─────────────── CONFIG ───────────────
MODE       = "LIVE"
BOT_TOKEN  = os.getenv("BOT_TOKEN")
CHAT_ID    = os.getenv("CHAT_ID")
CAPITAL    = 10.0           # Fixed $10 per trade
MIN_SCORE  = 65             # Skip below this
IST_OFFSET = timedelta(hours=5, minutes=30)

# ─────────────── GLOBAL CANDLE STORES ───────────────
candles_5m     = []
candles_15m    = []
candles_1h     = []
candles_4h     = []
candles_daily  = []

last_update_key = None
last_signal_key = None

# Refresh counters — avoid hammering API
_tf_refresh_tick = 0   # incremented each loop
TF_SLOW_EVERY   = 5    # refresh 1H/4H/Daily every 5 loops (~5 min)

# ─────────────── WEEKLY EVENT CALENDAR ───────────────
# Add THIS WEEK's events here every Sunday.
# Format: (weekday 0=Mon, utc_hour, utc_min, "name", "HIGH"/"MED")
# HIGH → ±30 min block | MED → ±15 min block
WEEKLY_EVENTS = [
    # Examples (uncomment & edit each week):
    # (4, 13, 30, "NFP",  "HIGH"),    # Friday 13:30 UTC
    # (2, 19,  0, "FOMC", "HIGH"),    # Wednesday 19:00 UTC
    # (1, 13, 30, "CPI",  "HIGH"),    # Tuesday  13:30 UTC
]


# ════════════════════════════════════════════════════════════
#  TELEGRAM
# ════════════════════════════════════════════════════════════
def send_msg(msg):
    try:
        print("📤", msg[:120])
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=10,
        )
    except Exception as e:
        print("❌ Telegram Error:", e)


# ════════════════════════════════════════════════════════════
#  TIME HELPERS
# ════════════════════════════════════════════════════════════
def now_utc():
    return datetime.now(timezone.utc)

def now_ist():
    return now_utc() + IST_OFFSET

def ist_str(dt=None):
    d = dt or now_ist()
    return d.strftime("%d %b %Y %I:%M %p IST")


# ════════════════════════════════════════════════════════════
#  STEP 4 — SESSION FILTER
#  Ref: https://www.worldtimeserver.com (UTC)
# ════════════════════════════════════════════════════════════
def get_session():
    """
    Returns (session_label, can_trade, reason)

    UTC Windows:
    ─────────────────────────────────────────────
    Asian body    03:00–07:00  ✅  Trade
    London open   07:00–07:30  ⚠️  Wait (volatile spike)
    London open   07:30–08:00  ✅  Trade (settled)
    London body   08:00–11:00  ✅  BEST session
    Lunch gap     11:00–13:00  ❌  Low liquidity
    NY open       13:00–13:30  ❌  Wait (first 30 min)
    NY body       13:30–16:00  ✅  Trade
    NY close      16:00–17:00  ❌  Block — no new trades
    Dead zone     17:00–03:00  ❌  No trades
    ─────────────────────────────────────────────
    Kill zones (best windows inside sessions):
      Asian kill   03:00–05:00 UTC / 08:30–10:30 IST
      London kill  08:00–10:00 UTC / 13:30–15:30 IST
      NY kill      13:30–15:30 UTC / 19:00–21:00 IST
    """
    utc   = now_utc()
    total = utc.hour * 60 + utc.minute

    def between(a, b):
        return a <= total < b

    # Dead zone (crosses midnight)
    if total >= 17 * 60 or total < 3 * 60:
        return "DEAD ZONE", False, "No trades 17:00–03:00 UTC"

    if between(3 * 60, 5 * 60):
        return "ASIAN KILL ZONE", True, "Asian kill zone 03:00–05:00 UTC"

    if between(5 * 60, 7 * 60):
        return "ASIAN BODY", True, "Asian body session"

    if between(7 * 60, 7 * 60 + 30):
        return "LONDON OPEN", False, "London open spike — wait 30 min"

    if between(7 * 60 + 30, 8 * 60):
        return "LONDON OPEN", True, "London open (post-spike OK)"

    if between(8 * 60, 10 * 60):
        return "LONDON KILL ZONE", True, "London kill zone — BEST window"

    if between(10 * 60, 11 * 60):
        return "LONDON BODY", True, "London body session"

    if between(11 * 60, 13 * 60):
        return "LUNCH GAP", False, "London–NY gap — low liquidity"

    if between(13 * 60, 13 * 60 + 30):
        return "NY OPEN", False, "NY open — wait first 30 min"

    if between(13 * 60 + 30, 15 * 60 + 30):
        return "NY KILL ZONE", True, "NY kill zone active"

    if between(15 * 60 + 30, 16 * 60):
        return "NY BODY", True, "NY body session"

    if between(16 * 60, 17 * 60):
        return "NY CLOSE", False, "NY close — no new trades"

    return "UNKNOWN", False, "Unknown session"


# ════════════════════════════════════════════════════════════
#  STEP 5 — EVENT FILTER
# ════════════════════════════════════════════════════════════
def is_event_blocked():
    """
    Returns (blocked: bool, reason: str)
    Checks WEEKLY_EVENTS list + hardcoded recurring windows.
    """
    utc     = now_utc()
    wday    = utc.weekday()   # 0 = Monday
    total   = utc.hour * 60 + utc.minute

    # 1) User-defined events for the week
    for ev in WEEKLY_EVENTS:
        ev_wday, ev_h, ev_m, ev_name, ev_impact = ev
        if wday == ev_wday:
            ev_total = ev_h * 60 + ev_m
            buf = 30 if ev_impact == "HIGH" else 15
            if abs(total - ev_total) <= buf:
                return True, f"{ev_name} ({ev_impact}) — ±{buf}min block"

    # 2) Auto-blocks: most common fixed-time events
    # NFP — first Friday 13:15–14:00 UTC (safe blanket)
    if wday == 4 and 13 * 60 + 15 <= total <= 14 * 60:
        return True, "Friday 13:15–14:00 UTC — potential NFP window"

    # FOMC — Wednesday 18:45–19:15 UTC
    if wday == 2 and 18 * 60 + 45 <= total <= 19 * 60 + 15:
        return True, "Wednesday 18:45–19:15 UTC — FOMC window"

    # CPI/PPI — typically Tuesday 13:15–13:45 UTC
    if wday == 1 and 13 * 60 + 15 <= total <= 13 * 60 + 45:
        return True, "Tuesday 13:15–13:45 UTC — CPI/PPI auto-block"

    return False, ""


# ════════════════════════════════════════════════════════════
#  DATA — COINBASE PUBLIC API
#  Response: [time, low, high, open, close, volume]
# ════════════════════════════════════════════════════════════
def fetch_candles(granularity=300):
    """Fetch up to 300 candles for the given granularity (seconds)."""
    url     = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
    headers = {"User-Agent": "Mozilla/5.0"}
    params  = {"granularity": granularity}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"  API [{granularity}s] HTTP {res.status_code}:", res.text[:80])
            return []
        raw = res.json()
        candles = []
        for d in raw:
            try:
                candles.append({
                    "time":   int(d[0]),
                    "low":    float(d[1]),
                    "high":   float(d[2]),
                    "open":   float(d[3]),
                    "close":  float(d[4]),
                    "volume": float(d[5]) if len(d) > 5 else 0.0,
                })
            except Exception:
                continue
        candles.sort(key=lambda x: x["time"])
        return candles
    except Exception as e:
        print(f"  ❌ Fetch [{granularity}s] failed:", e)
        return []


def refresh_all_timeframes(force=False):
    """
    STEP 1: Pull multi-TF candles.
    5m  → every loop (60s)
    15m → every 5 loops (~5 min)
    1H, 4H, Daily → every 5 loops (~5 min)
    Uses delay between calls to avoid rate-limiting.
    """
    global candles_5m, candles_15m, candles_1h, candles_4h, candles_daily
    global _tf_refresh_tick

    _tf_refresh_tick += 1

    # Always refresh 5m
    c5 = fetch_candles(300)
    if c5:
        candles_5m = c5

    if force or _tf_refresh_tick % TF_SLOW_EVERY == 0:
        time.sleep(0.5)
        c15 = fetch_candles(900)
        if c15:
            candles_15m = c15

        time.sleep(0.5)
        c1h = fetch_candles(3600)
        if c1h:
            candles_1h = c1h

        time.sleep(0.5)
        c4h = fetch_candles(14400)
        if c4h:
            candles_4h = c4h

        time.sleep(0.5)
        cd = fetch_candles(86400)
        if cd:
            candles_daily = cd


# ════════════════════════════════════════════════════════════
#  STEP 2 — 90-DAY ROLLING CSV
#  26 000 rows ≈ 90 days of 5m candles (90×24×12 = 25 920)
# ════════════════════════════════════════════════════════════
def update_csv(candles):
    path   = "btc_5m.csv"
    df_new = pd.DataFrame(candles)
    if os.path.exists(path):
        df_old = pd.read_csv(path)
        df = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df = df_new
    df = df.drop_duplicates(subset=["time"])
    df = df.sort_values("time").tail(26000)
    df.to_csv(path, index=False)


# ════════════════════════════════════════════════════════════
#  INDICATORS
# ════════════════════════════════════════════════════════════
def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    val = values[0]
    for v in values[1:]:
        val = v * k + val * (1 - k)
    return val


def calc_vwap(candles):
    if not candles:
        return None
    tp  = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles]
    vol = [max(c.get("volume", 1.0), 1e-9) for c in candles]
    total_vol = sum(vol)
    return sum(t * v for t, v in zip(tp, vol)) / total_vol


def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs[-period:]))


def vol_avg(candles, n=10):
    vols = [c.get("volume", 0.0) for c in candles[-(n + 1):-1]]
    avg  = float(np.mean(vols)) if vols else 0.0
    return avg if avg > 0 else 1e-9


def bullish(c):     return c["close"] > c["open"]
def bearish(c):     return c["close"] < c["open"]
def body(c):        return abs(c["close"] - c["open"])
def crange(c):      return c["high"] - c["low"]

def is_engulfing(c, prev):
    if bullish(c) and bearish(prev):
        return c["close"] > prev["open"] and c["open"] < prev["close"]
    if bearish(c) and bullish(prev):
        return c["open"] > prev["close"] and c["close"] < prev["open"]
    return False

def is_pin_bar(c):
    r = crange(c)
    return (r > 0) and (body(c) / r < 0.35)


# ════════════════════════════════════════════════════════════
#  STEP 2 — BIAS CHECK  (4H / Daily, 7–10 day lookback)
# ════════════════════════════════════════════════════════════
def get_bias():
    """
    BULLISH / BEARISH / FLAT based on 4H EMA20/50 + price position.
    7–10 day lookback = last 60 × 4H candles.
    Falls back to 5m if 4H not ready.
    """
    src = candles_4h if len(candles_4h) >= 20 else candles_5m
    if len(src) < 20:
        return "FLAT"

    closes = [c["close"] for c in src[-60:]]
    e20 = ema(closes[-20:], 20)
    e50 = ema(closes, 50) if len(closes) >= 50 else None
    last = closes[-1]

    if e20 and e50:
        if e20 > e50 and last > e20:
            return "BULLISH"
        if e20 < e50 and last < e20:
            return "BEARISH"
    elif e20:
        if last > e20 * 1.001:
            return "BULLISH"
        if last < e20 * 0.999:
            return "BEARISH"
    return "FLAT"


def get_trend_label():
    b = get_bias()
    strength = "WEAK"
    if len(candles_4h) >= 20:
        closes = [c["close"] for c in candles_4h[-20:]]
        e9  = ema(closes[-9:], 9)
        e20 = ema(closes, 20)
        if e9 and e20:
            pct = abs(e9 - e20) / e20 * 100
            strength = "STRONG" if pct > 1.5 else "MODERATE" if pct > 0.5 else "WEAK"
    return f"{b} ({strength})"


# ════════════════════════════════════════════════════════════
#  STEP 3 — ZONE DETECTION  (1H, 7–10 day lookback)
# ════════════════════════════════════════════════════════════
def get_zones():
    """Returns (resistance, support) from 1H highs/lows over ~3 days."""
    src = candles_1h[-72:] if len(candles_1h) >= 20 else candles_5m[-288:]
    if not src:
        src = candles_5m[-50:]
    resistance = max(c["high"]  for c in src)
    support    = min(c["low"]   for c in src)
    return resistance, support


def get_vwap_level():
    if len(candles_15m) >= 20:
        return calc_vwap(candles_15m[-48:])     # ~12h intraday VWAP
    return calc_vwap(candles_5m[-72:]) if candles_5m else None


# ════════════════════════════════════════════════════════════
#  STEP 6 — 5 STRATEGY MODULES
#  Each returns (signal, score, sl) or (None, 0, None)
#  Bias alignment boosts score; counter-bias disqualifies.
# ════════════════════════════════════════════════════════════

# ── 1. BREAKOUT + RETEST ──────────────────────────────────
def strategy_breakout_retest(bias):
    if len(candles_5m) < 3 or len(candles_1h) < 10:
        return None, 0, None

    highs_1h = [c["high"] for c in candles_1h[-20:]]
    lows_1h  = [c["low"]  for c in candles_1h[-20:]]
    zone_hi  = max(highs_1h)
    zone_lo  = min(lows_1h)

    c   = candles_5m[-1]
    p   = candles_5m[-2]
    va  = vol_avg(candles_5m)
    vol_ok = c.get("volume", 0) >= va * 1.5

    # Bullish retest
    if bias in ("BULLISH", "FLAT"):
        if p["close"] > zone_hi and c["low"] <= zone_hi <= c["close"] and bullish(c):
            score = 70
            if vol_ok:              score += 12
            if is_engulfing(c, p):  score += 10
            if bias == "BULLISH":   score += 8
            sl = zone_hi - abs(c["close"] - c["low"]) * 0.5
            return "BUY", min(score, 100), sl

    # Bearish retest
    if bias in ("BEARISH", "FLAT"):
        if p["close"] < zone_lo and c["high"] >= zone_lo >= c["close"] and bearish(c):
            score = 70
            if vol_ok:              score += 12
            if is_engulfing(c, p):  score += 10
            if bias == "BEARISH":   score += 8
            sl = zone_lo + abs(c["high"] - c["close"]) * 0.5
            return "SELL", min(score, 100), sl

    return None, 0, None


# ── 2. EMA PULLBACK (20/50) ──────────────────────────────
def strategy_ema_pullback(bias):
    src = candles_1h if len(candles_1h) >= 50 else candles_5m
    if len(src) < 50:
        return None, 0, None

    closes = [c["close"] for c in src]
    e20 = ema(closes[-20:], 20)
    e50 = ema(closes[-50:], 50)
    if not e20 or not e50:
        return None, 0, None

    c  = candles_5m[-1]
    p  = candles_5m[-2]
    va = vol_avg(candles_5m)
    vol_ok = c.get("volume", 0) >= va * 1.5

    # Bullish pullback to EMA20
    if e20 > e50 and bias == "BULLISH":
        proximity = abs(c["low"] - e20) / e20
        if proximity < 0.004:
            score = 68
            if is_pin_bar(c) or bullish(c): score += 8
            if vol_ok:                       score += 10
            if is_engulfing(c, p):           score += 10
            sl = e50 * 0.999
            return "BUY", min(score, 100), sl

    # Bearish pullback to EMA20
    if e20 < e50 and bias == "BEARISH":
        proximity = abs(c["high"] - e20) / e20
        if proximity < 0.004:
            score = 68
            if is_pin_bar(c) or bearish(c): score += 8
            if vol_ok:                       score += 10
            if is_engulfing(c, p):           score += 10
            sl = e50 * 1.001
            return "SELL", min(score, 100), sl

    return None, 0, None


# ── 3. VWAP BOUNCE ───────────────────────────────────────
def strategy_vwap_bounce(bias):
    vwap = get_vwap_level()
    if not vwap or len(candles_5m) < 3:
        return None, 0, None

    c  = candles_5m[-1]
    p  = candles_5m[-2]
    va = vol_avg(candles_5m)
    vol_ok  = c.get("volume", 0) >= va * 1.5
    near    = abs(c["close"] - vwap) / vwap < 0.002  # within 0.2%

    if not near:
        return None, 0, None

    atr = calc_atr(candles_5m) or 80

    if bullish(c) and bias in ("BULLISH", "FLAT"):
        score = 62
        if is_pin_bar(c) or is_engulfing(c, p): score += 12
        if vol_ok:                               score += 10
        if bias == "BULLISH":                    score += 8
        sl = vwap - atr * 0.6
        return "BUY", min(score, 100), sl

    if bearish(c) and bias in ("BEARISH", "FLAT"):
        score = 62
        if is_pin_bar(c) or is_engulfing(c, p): score += 12
        if vol_ok:                               score += 10
        if bias == "BEARISH":                    score += 8
        sl = vwap + atr * 0.6
        return "SELL", min(score, 100), sl

    return None, 0, None


# ── 4. LIQUIDITY GRAB (STOP HUNT) ────────────────────────
def strategy_liquidity_grab(bias):
    # 7–10 day 4H lookback for swing highs/lows
    src_lkb = candles_4h[-60:] if len(candles_4h) >= 10 else candles_1h[-168:]
    if len(src_lkb) < 5 or len(candles_5m) < 3:
        return None, 0, None

    hi_4h = max(c["high"] for c in src_lkb)
    lo_4h = min(c["low"]  for c in src_lkb)

    c  = candles_5m[-1]
    p  = candles_5m[-2]
    va = vol_avg(candles_5m)
    vol_ok = c.get("volume", 0) >= va * 1.5
    atr    = calc_atr(candles_5m) or 80

    # Bearish sweep: wick above 4H high, closes back below
    if c["high"] > hi_4h and c["close"] < hi_4h and bearish(c):
        score = 74
        if vol_ok:                       score += 12
        if is_engulfing(c, p):           score += 10
        if bias == "BEARISH":            score += 8
        # Counter-trend penalty
        if bias == "BULLISH":            score -= 15
        if score < MIN_SCORE:            return None, 0, None
        sl = c["high"] + atr * 0.5
        return "SELL", min(score, 100), sl

    # Bullish sweep: wick below 4H low, closes back above
    if c["low"] < lo_4h and c["close"] > lo_4h and bullish(c):
        score = 74
        if vol_ok:                       score += 12
        if is_engulfing(c, p):           score += 10
        if bias == "BULLISH":            score += 8
        if bias == "BEARISH":            score -= 15
        if score < MIN_SCORE:            return None, 0, None
        sl = c["low"] - atr * 0.5
        return "BUY", min(score, 100), sl

    return None, 0, None


# ── 5. RANGE TRAP → BREAKOUT ─────────────────────────────
def strategy_range_trap(bias):
    src = candles_1h[-20:] if len(candles_1h) >= 20 else candles_5m[-60:]
    if len(src) < 5 or len(candles_5m) < 3:
        return None, 0, None

    hi  = max(c["high"] for c in src)
    lo  = min(c["low"]  for c in src)
    rng = hi - lo

    # Must be genuine consolidation: range < 2.5% of price
    if lo == 0 or rng / lo > 0.025:
        return None, 0, None

    c  = candles_5m[-1]
    p  = candles_5m[-2]
    va = vol_avg(candles_5m)
    vol_ok = c.get("volume", 0) >= va * 1.5
    atr    = calc_atr(candles_5m) or 80

    # Bullish breakout
    if c["close"] > hi and bullish(c):
        score = 68
        if vol_ok:              score += 15   # volume critical for range breaks
        if is_engulfing(c, p):  score += 10
        if bias == "BULLISH":   score += 7
        if bias == "BEARISH":   score -= 20   # strong penalty
        if score < MIN_SCORE:   return None, 0, None
        sl = hi - atr * 0.4    # just inside range
        return "BUY", min(score, 100), sl

    # Bearish breakout
    if c["close"] < lo and bearish(c):
        score = 68
        if vol_ok:              score += 15
        if is_engulfing(c, p):  score += 10
        if bias == "BEARISH":   score += 7
        if bias == "BULLISH":   score -= 20
        if score < MIN_SCORE:   return None, 0, None
        sl = lo + atr * 0.4
        return "SELL", min(score, 100), sl

    return None, 0, None


# ════════════════════════════════════════════════════════════
#  STEP 6 — STRATEGY ENGINE  (auto-selects best setup)
# ════════════════════════════════════════════════════════════
STRATEGY_FUNCS = [
    ("Liquidity Grab",    strategy_liquidity_grab),
    ("Breakout Retest",   strategy_breakout_retest),
    ("EMA Pullback",      strategy_ema_pullback),
    ("VWAP Bounce",       strategy_vwap_bounce),
    ("Range Trap",        strategy_range_trap),
]

def strategy_engine(bias):
    best = {"signal": None, "score": 0, "sl": None, "name": "None"}
    for name, fn in STRATEGY_FUNCS:
        try:
            sig, score, sl = fn(bias)
            if sig and score > best["score"]:
                best = {"signal": sig, "score": score, "sl": sl, "name": name}
        except Exception as e:
            print(f"  Strategy [{name}] error:", e)
    return best


# ════════════════════════════════════════════════════════════
#  STEP 8 — WIN PROBABILITY
# ════════════════════════════════════════════════════════════
def win_probability(score, bias, signal):
    """Simple heuristic: score + bias alignment → TP hit %."""
    tp1 = 50 + max(0, score - 65) * 0.7
    tp2 = 38 + max(0, score - 65) * 0.55
    aligned = (signal == "BUY" and bias == "BULLISH") or \
              (signal == "SELL" and bias == "BEARISH")
    if aligned:
        tp1 += 10
        tp2 += 7
    return min(int(tp1), 88), min(int(tp2), 76)


# ════════════════════════════════════════════════════════════
#  SCORE LABEL
# ════════════════════════════════════════════════════════════
def score_label(score):
    if score >= 80:
        return "🔥 STRONG TRADE"
    if score >= 65:
        return "✅ GOOD TRADE"
    return "⚠️ SKIP"


# ════════════════════════════════════════════════════════════
#  STEP 8 — TRADE SIGNAL MESSAGE
# ════════════════════════════════════════════════════════════
def trade_signal_message(price, best, bias, resistance, support, session):
    signal  = best["signal"]
    sl      = best["sl"]
    score   = best["score"]

    risk    = abs(price - sl) if sl else 200
    risk    = max(risk, 10)    # safety floor

    if signal == "BUY":
        tp1 = price + risk * 3
        tp2 = price + risk * 4
    else:
        tp1 = price - risk * 3
        tp2 = price - risk * 4

    # Fixed $10 capital sizing
    qty        = CAPITAL / risk
    profit_tp1 = round(qty * risk * 3, 2)
    profit_tp2 = round(qty * risk * 4, 2)
    risk_pct   = round(risk / price * 100, 3)

    wp1, wp2 = win_probability(score, bias, signal)

    return (
        f"🚨 BTC TRADE SIGNAL\n"
        f"📅 {ist_str()}\n"
        f"📍 Session: {session}\n"
        f"\n"
        f"Type: {'BUY 📈' if signal == 'BUY' else 'SELL 📉'}\n"
        f"Current Price: ${price:,.0f}\n"
        f"Entry: ${price:,.0f}\n"
        f"Capital: ${CAPITAL:.0f} fixed\n"
        f"\n"
        f"SL:  ${sl:,.0f}   (Risk {risk_pct}%)\n"
        f"TP1: ${tp1:,.0f}  (Profit ${profit_tp1} → RR 1:3)\n"
        f"TP2: ${tp2:,.0f}  (Profit ${profit_tp2} → RR 1:4)\n"
        f"\n"
        f"📊 Market Context:\n"
        f"Bias: {bias}\n"
        f"Strategy: {best['name']}\n"
        f"Score: {score}/100 → {score_label(score)}\n"
        f"Resistance: ${resistance:,.0f} | Support: ${support:,.0f}\n"
        f"\n"
        f"📈 Win Probability:\n"
        f"TP1 Hit: {wp1}% ✅  |  TP2 Hit: {wp2}% 🎯\n"
        f"\n"
        f"🛡️ Exit Rules:\n"
        f"TP1 hit → Close 50%, move SL to breakeven\n"
        f"TP2 hit → Close remaining position\n"
        f"Safe exit if invalidation candle prints"
    )


# ════════════════════════════════════════════════════════════
#  STEP 10 — SMART UPDATE (every 5 min)
# ════════════════════════════════════════════════════════════
def smart_update_message(price, candle, bias, best,
                         resistance, support, session,
                         event_blocked, event_reason):
    if event_blocked:
        status = "⛔ EVENT BLOCKED"
    elif best["signal"] and best["score"] >= 80:
        status = "🔥 SIGNAL ACTIVE"
    elif best["signal"] and best["score"] >= 65:
        status = "✅ MONITORING"
    else:
        status = "⏳ WAITING FOR SETUP"

    sig_line = (
        f"Signal: {best['signal']} | Score: {best['score']}/100 | {score_label(best['score'])}"
        if best["signal"]
        else "Signal: ⏳ Waiting for confirmation"
    )

    ev_line = f"⚠️ {event_reason}" if event_blocked else ""

    return (
        f"📊 BTC SMART UPDATE\n"
        f"📅 {ist_str()}\n"
        f"📍 Session: {session}\n"
        f"Status: {status}\n"
        f"\n"
        f"Trend Bias: {get_trend_label()}\n"
        f"Current Price: ${price:,.0f}\n"
        f"Resistance: ${resistance:,.0f} | Support: ${support:,.0f}\n"
        f"\n"
        f"Last 5m Candle:\n"
        f"  High:  ${candle['high']:,.0f}  |  Low:   ${candle['low']:,.0f}\n"
        f"  Open:  ${candle['open']:,.0f}  |  Close: ${candle['close']:,.0f}\n"
        f"  Vol:   {candle.get('volume', 0):.2f}\n"
        f"\n"
        f"Strategy Setup: {best['name']}\n"
        f"{sig_line}\n"
        + (f"{ev_line}\n" if ev_line else "")
    )


# ════════════════════════════════════════════════════════════
#  MAIN LOOP
# ════════════════════════════════════════════════════════════
send_msg(
    "🚀 BTC BOT STARTED\n"
    "✅ Session filter | Event block | Multi-TF | 90-Day CSV\n"
    "Capital: $10 fixed | Score min: 65 | RR 1:3 / 1:4"
)

while True:
    try:
        now = now_ist()

        # ── STEP 1: Fetch all timeframes + 90-day CSV ──
        refresh_all_timeframes()

        if not candles_5m:
            time.sleep(10)
            continue

        update_csv(candles_5m)

        price  = candles_5m[-1]["close"]
        candle = candles_5m[-1]

        # ── STEP 4: Session filter ──
        session, can_trade_session, session_reason = get_session()

        # ── STEP 5: Event filter ──
        event_blocked, event_reason = is_event_blocked()

        can_trade = can_trade_session and not event_blocked

        # ── STEP 2: Bias check (4H/Daily lookback) ──
        bias = get_bias()

        # ── STEP 3: Zone detection (1H) ──
        resistance, support = get_zones()

        # ── STEP 6 + 7: Strategy engine + entry trigger ──
        best = strategy_engine(bias)

        # ── STEP 8: Trade signal ──
        if can_trade and best["signal"] and best["score"] >= MIN_SCORE:
            # Deduplicate: one signal per strategy+direction per hour
            sig_key = f"{now.strftime('%Y%m%d%H')}-{best['name']}-{best['signal']}"
            if sig_key != last_signal_key:
                last_signal_key = sig_key
                send_msg(trade_signal_message(
                    price, best, bias, resistance, support, session
                ))

        # ── STEP 10: Smart update every 5 min ──
        if now.minute % 15 == 0:
            key = f"{now.hour}:{now.minute}"
            if last_update_key != key:
                last_update_key = key
                send_msg(smart_update_message(
                    price, candle, bias, best,
                    resistance, support, session,
                    event_blocked, event_reason
                ))

        time.sleep(60)

    except Exception as e:
        print("MAIN LOOP ERROR:", e)
        traceback.print_exc()
        time.sleep(10)
