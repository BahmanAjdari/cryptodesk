"""اجرای لایو (پول واقعی!) — python scripts/run_live.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml
from src.nobitex_client import NobitexClient
from src.trader import Trader

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

token = os.getenv("NOBITEX_TOKEN", "")
if not token:
    print("NOBITEX_TOKEN ست نشده. در .env بگذار.")
    sys.exit(1)
confirm = input("معامله واقعی با پول واقعی انجام می‌شود. مطمئنی؟ (yes/no): ")
if confirm.strip().lower() != "yes":
    print("لغو شد."); sys.exit(0)

cfg["execution"]["dry_run"] = False
Trader(cfg, NobitexClient(cfg["base_url"], token=token)).run()
