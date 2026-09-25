"""دیمن پس‌زمینه پورتفوی مجازی — جدا از داشبورد اجرا می‌شود تا قطع شدن مرورگر
یا بستن ترمینال معاملات را متوقف نکند.

خواندن تنظیمات از paper_state.json در هر دور:
  active=True → هر interval_min دقیقه یک اسکن
  فایل paper_scan.flag → یک اسکن فوری (دکمه «همین الان اسکن کن» در داشبورد)
گزارش: paper_daemon.log | ضربان: daemon_heartbeat.json
"""
import os
import sys
import time
import json
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import yaml

HEARTBEAT = os.path.join(BASE, "daemon_heartbeat.json")
FLAG = os.path.join(BASE, "paper_scan.flag")


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def main():
    from src.nobitex_client import NobitexClient
    from src.paper import load, save, scan_step

    with open(os.path.join(BASE, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    client = NobitexClient(cfg["base_url"])
    log("daemon started")

    while True:
        try:
            with open(HEARTBEAT, "w") as f:
                json.dump({"time": time.time()}, f)
            with open(os.path.join(BASE, "config.yaml")) as f:
                cfg = yaml.safe_load(f)  # هر دور تازه بخوان تا تغییر داشبورد نیاز به ری‌استارت نداشته باشد
            acct = load()
            if acct is not None:
                interval = int(acct.get("interval_min", 15))
                now = time.time()
                forced = os.path.exists(FLAG)
                due = acct.get("active") and acct.get("next_scan", 0) <= now
                if forced or due:
                    if forced and os.path.exists(FLAG):
                        os.remove(FLAG)
                    log("scan started")
                    scan_step(acct, client, cfg, verbose=log)
                    acct = load() or acct
                    acct["next_scan"] = time.time() + interval * 60
                    save(acct)
                    log("scan done")
                    _maybe_daily_report(acct)
            _maybe_new_listings(client)
        except Exception:
            log("ERROR:\n" + traceback.format_exc())
        time.sleep(15)


def _maybe_new_listings(client):
    """چک روزانه لیست‌شدن کوین جدید در نوبیتکس + پیام بله (یک بار در روز)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        from src.discover import newly_listed
        from src.notify import get_notifier
        teh = datetime.now(ZoneInfo("Asia/Tehran"))
        mark_path = os.path.join(BASE, ".listing_check")
        today = teh.date().isoformat()
        if os.path.exists(mark_path) and open(mark_path).read().strip() == today:
            return
        new = newly_listed(client)
        open(mark_path, "w").write(today)
        if new:
            n = get_notifier()
            if n:
                try:
                    n.send("🆕 کوین جدید در نوبیتکس لیست شد:\n" + "، ".join(new[:20]) +
                           "\nاز بخش «کوین‌های جدید» در تب اسکرینر با یک تیک اضافه‌شان کن.")
                except Exception as e:
                    log(f"listing notify failed: {e}")
            log(f"new listings: {new}")
    except Exception as e:
        log(f"listing check failed: {e}")


def _maybe_daily_report(acct):
    """گزارش روزانه به بله: هر روز یک بار بعد از ساعت ۲۳ تهران."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        from src.paper import save, equity
        from src.notify import get_notifier
        teh = datetime.now(ZoneInfo("Asia/Tehran"))
        today = teh.date().isoformat()
        if acct.get("last_report") == today or teh.hour < 23:
            return
        notify = get_notifier()
        if not notify:
            return
        import pandas as pd

        def _exit_day(t):
            try:
                et = t.get("exit_time")
                if not et:
                    return None
                return pd.Timestamp(et).tz_convert("Asia/Tehran").date().isoformat()
            except Exception:
                return None

        closed_today = [t for t in acct.get("history", []) if _exit_day(t) == today]
        prices = acct.get("last_prices", {})
        eq = equity(acct, prices) if prices else acct.get("cash", 0)
        h = acct.get("history", [])
        notify.daily_report(eq, acct["starting_cash"], closed_today,
                            len(acct.get("positions", {})), len(h),
                            sum(1 for t in h if t.get("pnl", 0) > 0))
        acct["last_report"] = today
        save(acct)
        log("daily report sent")
    except Exception as e:
        log(f"daily report failed: {e}")


if __name__ == "__main__":
    main()
