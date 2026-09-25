"""بک‌تست همه کوین‌ها + انتخاب بهترین — اجرا: python scripts/backtest_all.py [--tf 60]"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import argparse
import yaml
from src.nobitex_client import NobitexClient
from src.strategies import apply_all
from src.backtest import grid_search
from src.screener import screen

ap = argparse.ArgumentParser()
ap.add_argument("--tf", default=None, help="تایم‌فریم بک‌تست (پیش‌فرض: 60 برای تاریخچه عمیق)")
args = ap.parse_args()

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

# نوبیتکس برای 15m فقط ~۷ روز تاریخچه می‌دهد؛ برای بک‌تست معنادار از 60m استفاده کن
tf = args.tf or "60"
total = 2000 if tf in ("60", "240", "D") else 1000

client = NobitexClient(cfg["base_url"])
data = {}
for sym in cfg["symbols"]:
    print(f"fetch {sym} ({tf}) ...")
    try:
        data[sym] = client.klines_history(sym, tf, total=total)
        print(f"  {len(data[sym])} candles "
              f"({data[sym]['time'].min()} -> {data[sym]['time'].max()})")
    except Exception as e:
        print(f"  FAIL: {e}")

print("\n===== RANKING =====")
table = screen(data, cfg)
print(table.to_string())

print("\n===== DETAIL PER SYMBOL (tuned SL/TP) =====")
for sym, raw in data.items():
    df = apply_all(raw)
    g = grid_search(df)
    print(f"\n--- {sym} ---")
    print(g.head(3).to_string())
