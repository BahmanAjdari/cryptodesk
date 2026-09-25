"""پورتفوی مجازی: پول فرضی (تومان) + خرید/فروش خودکار با سیگنال بات + ذخیره‌سازی دائمی.

- بازارها: نسخه IRT (تومانی) کوین‌ها — مستقیم با تومان کار می‌کند.
- وضعیت در paper_state.json ذخیره می‌شود تا با رفرش صفحه از بین نرود.
- هر اسکن: مدیریت پوزیشن‌های باز (SL/TP/سیگنال/زمان) → گیت اخبار → ورودهای جدید.
"""
import json
import os
import time
import pandas as pd

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "paper_state.json")


def irt_symbol(coin: str) -> str:
    return f"{coin.upper()}IRT"


def new_account(capital_toman: float) -> dict:
    return {
        "active": True,
        "starting_cash": float(capital_toman),
        "cash": float(capital_toman),
        "positions": {},   # symbol -> {entry, amount, sl, tp, bars, entry_time, peak}
        "history": [],     # معاملات بسته‌شده
        "snapshots": [],   # [{time, equity}]
        "last_scan": None,
    }


def save(acct: dict, path=STATE_FILE):
    with open(path, "w") as f:
        json.dump(acct, f, default=str)


def load(path=STATE_FILE):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def equity(acct: dict, prices: dict) -> float:
    eq = acct["cash"]
    for sym, p in acct["positions"].items():
        eq += p["amount"] * prices.get(sym, p["entry"])
    return eq


def _teh_day(ts):
    """روز به‌وقت تهران برای یک زمان ISO (naive = UTC)."""
    try:
        if not ts:
            return None
        import pandas as pd
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return t.tz_convert("Asia/Tehran").date().isoformat()
    except Exception:
        return None


def scan_step(acct: dict, client, cfg: dict, coins=None, verbose=print,
              notify_opt=True) -> dict:
    """یک دور کامل: چک خروج‌ها + ورودهای جدید. تغییرات را در acct اعمال و ذخیره می‌کند.
    notify_opt=False پیام بله نمی‌فرستد (برای تست‌ها)."""
    from .strategies import apply_all
    from .screener import screen
    from . import news as newsmod
    from .notify import get_notifier
    notify = get_notifier() if notify_opt else None

    coins = coins or acct.get("coins") or cfg.get("paper_coins",
                ["BTC", "ETH", "SOL", "DOGE", "XRP", "BNB", "AVAX", "TRX", "LINK", "LTC", "USDT"])
    r = cfg["risk"]
    fee = r["fee_pct"] / 100
    tf = str(acct.get("timeframe", cfg["timeframe"]))
    thr = float(acct.get("min_score", cfg["screener"]["min_signal_score"]))
    max_pos = int(acct.get("max_open_positions", r["max_open_positions"]))
    sl_m = float(acct.get("sl_atr", r["sl_atr_mult"]))
    tp_m = float(acct.get("tp_atr", r["tp_atr_mult"]))
    trail_m = float(acct.get("trail_atr", r.get("trailing_atr_mult", 0.0) or 0.0))
    kill_drop = float(acct.get("kill_drop_pct", r.get("kill_drop_pct", 3.0)))
    kill_cool_h = float(acct.get("kill_cool_h", r.get("kill_cool_h", 4)))
    day_loss_lim = float(acct.get("max_daily_loss_pct", r.get("max_daily_loss_pct", 3.0)))

    # --- دریافت داده ---
    data, frames = {}, {}
    for coin in coins:
        sym = irt_symbol(coin)
        try:
            raw = client.klines(sym, tf, 500)
            data[sym] = raw
            frames[sym] = apply_all(raw, min_score=thr)
            time.sleep(0.2)
        except Exception as e:
            verbose(f"[!] {sym}: {e}")
    if not data:
        return acct
    prices = {s: float(frames[s].iloc[-1]["c"]) for s in frames}
    import time as _t
    now_ts = _t.time()

    # --- کلید اضطراری: ریزش تند BTC در ۶۰ دقیقه اخیر → بستن فوری همه ---
    panic_drop = None
    if kill_drop > 0 and "BTCIRT" in frames:
        bdf = frames["BTCIRT"]
        end = bdf["time"].max()
        ref_row = bdf.iloc[(bdf["time"] - (end - pd.Timedelta(minutes=60))).abs().argsort()[:1]]
        ref = float(ref_row.iloc[0]["c"])
        drop = (prices["BTCIRT"] / ref - 1) * 100
        if drop <= -kill_drop:
            panic_drop = drop
    cooling = acct.get("kill_until", 0) > now_ts
    if panic_drop is not None and acct["positions"]:
        for sym in list(acct["positions"]):
            p = acct["positions"][sym]
            px = prices.get(sym, p["entry"])
            proceeds = p["amount"] * px * (1 - fee)
            pnl = proceeds - p["cost"]
            acct["cash"] += proceeds
            acct["history"].append({
                "symbol": sym, "entry": p["entry"], "exit": px,
                "entry_time": p.get("entry_time"), "exit_time": str(frames[sym].iloc[-1]["time"]),
                "bars": p.get("bars", 0),
                "reason": "PANIC", "pnl": round(pnl, 0),
                "pnl_pct": round(pnl / p["cost"] * 100, 2),
            })
            del acct["positions"][sym]
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        acct["kill_until"] = (datetime.now(ZoneInfo("Asia/Tehran")) + timedelta(hours=kill_cool_h)).timestamp()
        cooling = True
        verbose(f"[PANIC] BTC {panic_drop:.2f}% در ۶۰ دقیقه — همه بسته شد، خنک‌سازی {kill_cool_h} ساعت")
        if notify:
            try:
                notify.kill_switch(panic_drop, kill_cool_h)
            except Exception as e:
                verbose(f"[!] ارسال پیام بله ناموفق: {e}")

    # --- سقف ضرر روزانه (به‌وقت تهران) ---
    halted = acct.get("halted_until", 0) > now_ts
    if not halted and day_loss_lim > 0:
        from zoneinfo import ZoneInfo
        from datetime import datetime, timedelta
        teh = datetime.now(ZoneInfo("Asia/Tehran"))
        today = teh.date().isoformat()
        realized = sum(t.get("pnl", 0) for t in acct.get("history", [])
                       if _teh_day(t.get("exit_time")) == today)
        unreal = sum((prices.get(s, p["entry"]) - p["entry"]) * p["amount"]
                     for s, p in acct["positions"].items())
        day_pnl = realized + unreal
        snaps = [s for s in acct.get("snapshots", [])
                 if _teh_day(s.get("time")) == today]
        ref_eq = snaps[0]["equity"] if snaps else acct.get("starting_cash", 1)
        if day_pnl <= -day_loss_lim / 100 * ref_eq:
            nxt = (teh.date() + timedelta(days=1))
            midnight = datetime(nxt.year, nxt.month, nxt.day, tzinfo=ZoneInfo("Asia/Tehran")).timestamp()
            acct["halted_until"] = midnight
            halted = True
            verbose(f"[HALT] ضرر امروز {day_pnl:,.0f} به سقف رسید — توقف تا فردا")
            if notify:
                try:
                    notify.daily_halt(day_pnl, day_loss_lim)
                except Exception as e:
                    verbose(f"[!] ارسال پیام بله ناموفق: {e}")

    # --- مدیریت خروج‌ها (هر کندل بسته‌شده فقط یک بار) ---
    seen = acct.setdefault("seen", {})
    for sym in list(acct["positions"]):
        if sym not in frames:
            continue
        bar_t = str(frames[sym].iloc[-1]["time"])
        if seen.get(sym) == bar_t:
            continue  # این کندل در اسکن قبلی پردازش شده؛ شمارنده و حدها دوباره حساب نمی‌شود
        seen[sym] = bar_t
        p = acct["positions"][sym]
        row = frames[sym].iloc[-1]
        price = float(row["c"])
        atr = float(row["atr14"]) if pd.notna(row["atr14"]) else 0.0
        p["bars"] = p.get("bars", 0) + 1
        if trail_m > 0 and atr > 0:
            p["peak"] = max(p.get("peak", p["entry"]), float(row["h"]))
            p["sl"] = max(p["sl"], p["peak"] - trail_m * atr)
        reason = None
        if row["l"] <= p["sl"]:
            reason, exit_px = "SL", p["sl"]
        elif row["h"] >= p["tp"]:
            reason, exit_px = "TP", p["tp"]
        elif bool(row.get("exit_long", False)):
            reason, exit_px = "SIGNAL", price
        elif p["bars"] >= r["max_holding_candles"]:
            reason, exit_px = "TIME", price
        if reason:
            proceeds = p["amount"] * exit_px * (1 - fee)
            pnl = proceeds - p["cost"]
            acct["cash"] += proceeds
            acct["history"].append({
                "symbol": sym, "entry": p["entry"], "exit": exit_px,
                "entry_time": p.get("entry_time"), "exit_time": str(row["time"]),
                "bars": p["bars"],
                "reason": reason, "pnl": round(pnl, 0),
                "pnl_pct": round(pnl / p["cost"] * 100, 2),
            })
            del acct["positions"][sym]
            verbose(f"[EXIT:{reason}] {sym} pnl={pnl:,.0f} تومان")
            if notify:
                try:
                    notify.exit(sym, p["entry"], exit_px, p["cost"], pnl, reason)
                except Exception as e:
                    verbose(f"[!] ارسال پیام بله ناموفق: {e}")

    # --- گیت ورود ---
    try:
        fg = newsmod.fear_greed(cfg["news"]["fear_greed_url"])
        btc = frames.get("BTCIRT", frames.get("BTCUSDT"))
        reg = newsmod.market_regime(btc, cfg["regime"]["adx_trend_threshold"]) if btc is not None else {"regime": "range"}
        gate = newsmod.trade_gate(cfg, fg, {"score": 0, "n": 0}, reg)
    except Exception as e:
        gate = {"allow": False, "reasons": [str(e)]}
    verbose("GATE: " + " | ".join(gate["reasons"]))

    # --- ورودهای جدید ---
    eq = equity(acct, prices)
    table = screen({s: data[s] for s in data}, cfg)
    would_enter = [row["symbol"] for _, row in table.iterrows()
                   if row["symbol"] not in acct["positions"]
                   and row.get("enter_now", False) and row["score_now"] >= thr]
    entered = set()
    entries_ok = gate["allow"] and not cooling and not halted
    if entries_ok and len(acct["positions"]) < max_pos:
        for _, row in table.iterrows():
            sym = row["symbol"]
            if sym in acct["positions"] or not row.get("enter_now", False):
                continue
            if row["score_now"] < thr:
                continue
            last = frames[sym].iloc[-1]
            price, atr = float(last["c"]), float(last["atr14"])
            if not (atr > 0):
                continue
            risk_amt = eq * r["trade_risk_pct"] / 100
            notional = min(risk_amt / (sl_m * atr / price),
                           eq / max_pos, acct["cash"])
            if notional < 1_000_000:  # حداقل ۱ میلیون تومان
                continue
            cost = notional
            acct["cash"] -= cost
            amt = (cost * (1 - fee)) / price
            acct["positions"][sym] = {
                "entry": price, "amount": amt, "cost": cost,
                "sl": price - sl_m * atr,
                "tp": price + tp_m * atr,
                "bars": 0, "peak": price,
                "entry_time": str(frames[sym].iloc[-1]["time"]),
            }
            verbose(f"[ENTER] {sym} @ {price:,.0f} مبلغ {cost:,.0f} تومان")
            entered.add(sym)
            if notify:
                try:
                    pos = acct["positions"][sym]
                    notify.enter(sym, cost, price, pos["sl"], pos["tp"])
                except Exception as e:
                    verbose(f"[!] ارسال پیام بله ناموفق: {e}")
            if len(acct["positions"]) >= max_pos:
                break

    # --- پیام سیگنال بلاک‌شده (فقط نمادهایی که واقعاً جا ماندند) ---
    blocked = [s for s in would_enter if s not in entered and s not in acct["positions"]]
    if blocked and notify:
        if cooling:
            why = "دوره خنک‌سازی بعد از ریزش تند (کیل‌سوییچ)"
        elif halted:
            why = "سقف ضرر روزانه فعال است (توقف تا فردا)"
        elif not gate["allow"]:
            why = "بازار بلاک است (" + " | ".join(gate["reasons"]) + ")"
        else:
            why = "ظرفیت پورتفو پر است (سقف کوین هم‌زمان)"
        import time as _t
        last = acct.get("last_sig_msg", {})
        if _t.time() - last.get("time", 0) > 6 * 3600 or set(last.get("symbols", [])) != set(blocked):
            try:
                notify.signal_blocked(blocked, why)
                acct["last_sig_msg"] = {"time": _t.time(), "symbols": blocked}
            except Exception as e:
                verbose(f"[!] ارسال پیام بله ناموفق: {e}")

    # --- لیگ استراتژی‌ها ---
    try:
        from .league import new_league, step_league, ensure_league
        if "league" not in acct:
            acct["league"] = new_league()
        else:
            acct["league"] = ensure_league(acct["league"])
        step_league(acct["league"], frames, cfg, gate["allow"], verbose)
    except Exception as e:
        verbose(f"[!] league: {e}")

    # --- اسنپشات ---
    now = pd.Timestamp.utcnow().isoformat()
    acct["last_scan"] = now
    acct["last_prices"] = prices
    acct["snapshots"].append({"time": now, "equity": round(equity(acct, prices), 0)})
    save(acct)
    return acct
