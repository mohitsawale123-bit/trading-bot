import requests
import zipfile
import io
import csv
from datetime import datetime, timedelta

SYMBOL = "BTCUSDT"
INTERVAL = "1m"   # change to "5m" later
DAYS = 90

BASE_URL = "https://data.binance.vision/data/spot/daily/klines"

all_rows = {}
end_date = datetime.utcnow().date()

for i in range(DAYS):
    day = end_date - timedelta(days=i)
    date_str = day.strftime("%Y-%m-%d")

    url = f"{BASE_URL}/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{date_str}.zip"
    print("⬇️ Downloading:", date_str)

    try:
        r = requests.get(url, timeout=20)

        if r.status_code != 200:
            print("❌ Missing:", date_str)
            continue

        z = zipfile.ZipFile(io.BytesIO(r.content))
        file_name = z.namelist()[0]

        with z.open(file_name) as f:
            reader = csv.reader(io.TextIOWrapper(f))

            for row in reader:
                ts = int(row[0]) // 1000

                all_rows[ts] = {
                    "time": ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4])
                }

    except Exception as e:
        print("⚠️ Error:", e)

# SORT DATA
sorted_rows = sorted(all_rows.values(), key=lambda x: x["time"])

# SAVE FILE
out_file = f"btc_{INTERVAL}.csv"

with open(out_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["time", "open", "high", "low", "close"])

    for r in sorted_rows:
        writer.writerow([r["time"], r["open"], r["high"], r["low"], r["close"]])

print("✅ DONE:", out_file)
