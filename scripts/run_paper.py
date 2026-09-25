"""اجرای پیپر (بدون پول واقعی) — python scripts/run_paper.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yaml
from src.nobitex_client import NobitexClient
from src.trader import Trader

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)
cfg["execution"]["dry_run"] = True
Trader(cfg, NobitexClient(cfg["base_url"])).run()
