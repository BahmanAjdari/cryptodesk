"""لیگ استراتژی‌ها: هر ۴ استراتژی با ۱۰۰ میلیون جدا معامله مجازی می‌کند تا معلوم شود کدام بهتر است.

قوانین یکسان و شفاف برای هر ۴ نفر:
- ورود: وقتی سیگنال همان استراتژی +۱ شود
- خروج: حد ضرر ۱.۵×ATR / حد سود ۲.۵×ATR / سیگنال خروج همان استراتژی / ۹۶ کندل
- سایز: ریسک ۱٪ موجودی + سقف ۲ پوزیشن + کارمزد ۰.۱٪
"""
import time
import pandas as pd

CAPITAL_EACH = 100_000_000

STRATS = {
    "trend": {"fa": "۱) روند (EMA+MACD)", "sig": "sig_trend", "exit": "exit_trend"},
    "meanrev": {"fa": "۲) میانگین‌بازگشتی (RSI)", "sig": "sig_mr", "exit": "exit_mr"},
    "breakout": {"fa": "۳) بریک‌اوت", "sig": "sig_brk", "exit": "exit_brk"},
    "squeeze": {"fa": "۴) اسکوییز بولینگر", "sig": "sig_sqz", "exit": "exit_sqz"},
}

RULES_FA = (
    "قوانین مسابقه (برای هر ۴ نفر یکسان): ورود با سیگنال +۱ همان استراتژی | "
    "خروج: حد ضرر ۱.۵×ATR، حد سود ۲.۵×ATR، سیگنال خروج، یا ۹۶ کندل | "
    "سرمایه هر کدام ۱۰۰ میلیون تومان | ریسک ۱٪ + حداکثر ۲ پوزیشن"
)


def new_league() -> dict:
    return {name: {"cash": float(CAPITAL_EACH), "positions": {}, "history": []}
            for name in STRATS}


def step_league(league: dict, frames: dict, cfg: dict, gate_allow: bool, verbose=print):
    """یک دور برای هر ۴ استراتژی. frames: {symbol: df(has sig/exit/atr14/exit_long)}"""
    r = cfg["risk"]
    fee = r["fee_pct"] / 100
    prices = {s: float(frames[s].iloc[-1]["c"]) for s in frames}
    for name, meta in STRATS.items():
        st = league[name]
        seen = st.setdefault("seen", {})
        # خروج‌ها (هر کندل فقط یک بار)
        for sym in list(st["positions"]):
            if sym not in frames:
                continue
            bar_t = str(frames[sym].iloc[-1]["time"])
            if seen.get(sym) == bar_t:
                continue
            seen[sym] = bar_t
            p = st["positions"][sym]
            row = frames[sym].iloc[-1]
            price = float(row["c"])
            atr = float(row["atr14"]) if pd.notna(row["atr14"]) else 0.0
            if atr <= 0:
                continue
            p["bars"] = p.get("bars", 0) + 1
            reason, exit_px = None, price
            if row["l"] <= p["sl"]:
                reason, exit_px = "SL", p["sl"]
            elif row["h"] >= p["tp"]:
                reason, exit_px = "TP", p["tp"]
            elif bool(row.get(meta["exit"], False)):
                reason, exit_px = "SIGNAL", price
            elif p["bars"] >= r["max_holding_candles"]:
                reason, exit_px = "TIME", price
            if reason:
                proceeds = p["amount"] * exit_px * (1 - fee)
                pnl = proceeds - p["cost"]
                st["cash"] += proceeds
                st["history"].append({"symbol": sym, "entry": p["entry"], "exit": exit_px,
                                      "exit_time": str(row["time"]),
                                      "reason": reason, "pnl": round(pnl, 0),
                                      "pnl_pct": round(pnl / p["cost"] * 100, 2)})
                del st["positions"][sym]
                verbose(f"[LEAGUE:{name} EXIT:{reason}] {sym} {pnl:+,.0f}")
        # ورودها
        if not gate_allow or len(st["positions"]) >= 2:
            continue
        eq = st["cash"] + sum(p["amount"] * prices.get(s, p["entry"]) for s, p in st["positions"].items())
        for sym, df in frames.items():
            if sym in st["positions"]:
                continue
            last = df.iloc[-1]
            if not bool(last[meta["sig"]] > 0):
                continue
            price, atr = float(last["c"]), float(last["atr14"])
            if not (atr > 0):
                continue
            risk_amt = eq * r["trade_risk_pct"] / 100
            notional = min(risk_amt / (r["sl_atr_mult"] * atr / price), eq / 2, st["cash"])
            if notional < 1_000_000:
                continue
            st["cash"] -= notional
            st["positions"][sym] = {
                "entry": price, "amount": (notional * (1 - fee)) / price, "cost": notional,
                "sl": price - r["sl_atr_mult"] * atr, "tp": price + r["tp_atr_mult"] * atr,
                "bars": 0, "entry_time": str(last["time"]),
            }
            verbose(f"[LEAGUE:{name} ENTER] {sym} @ {price:,.0f}")
            if len(st["positions"]) >= 2:
                break
            time.sleep(0)
    return league


def league_equity(st: dict, prices: dict) -> float:
    return st["cash"] + sum(p["amount"] * prices.get(s, p["entry"]) for s, p in st["positions"].items())


def league_stats(st: dict, prices: dict) -> dict:
    eq = league_equity(st, prices)
    h = st["history"]
    wins = sum(1 for t in h if t["pnl"] > 0)
    return {"equity": round(eq, 0), "ret_pct": round((eq / CAPITAL_EACH - 1) * 100, 2),
            "n": len(h), "winrate": round(wins / len(h) * 100, 1) if h else 0.0,
            "n_open": len(st["positions"])}
