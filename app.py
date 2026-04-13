from flask import Flask, request
import requests
import os
from datetime import datetime

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

risk_per_trade = 1
trade_count = 0

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def calc_lot(entry, sl):
    sl_dist = abs(entry - sl)
    lot = risk_per_trade / (sl_dist * 100)
    return round(max(min(lot, 0.02), 0.001), 3)

@app.route('/webhook', methods=['POST'])
def webhook():
    global trade_count

    data = request.json
    entry = float(data["entry"])
    sl = float(data["sl"])
    tp = float(data["tp"])
    symbol = data["symbol"]

    lot = calc_lot(entry, sl)

    msg = f"""
📊 TRADE ALERT

Asset: {symbol}
Entry: {entry}
SL: {sl}
TP: {tp}

Lot: {lot}
Risk: -$1
Profit: +$3
"""
    send_telegram(msg)

    return {"status": "ok"}

app.run(host="0.0.0.0", port=5000)
