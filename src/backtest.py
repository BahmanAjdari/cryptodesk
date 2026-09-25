"""بک‌تستر لانگ اسپات — واقع‌گرایانه:
- سیگنال کندل i در بازگشایی کندل i+1 اجرا می‌شود (نه قیمت بسته شدن همان کندل)
- لغزش قیمت (slippage) در ورود/خروج + کارمزد هر دو سمت
- حد ضرر/حد سود ATR، تریلینگ، خروج زمانی (بدون هلد)
"""
import numpy as np
import pandas as pd


def backtest(df: pd.DataFrame, sl_atr=1.5, tp_atr=2.5, trailing_atr=0.0,
             fee_pct=0.1, max_holding=96, risk_pct=1.0,
             slippage_pct=0.05) -> dict:
    df = df.dropna().reset_index(drop=True)
    cash, equity_curve, trades = 10000.0, [], []
    pos = None  # dict(entry, sl, tp, notional, bars, peak, entry_idx)
    pending = None  # سیگنال ورود ثبت‌شده که در بازگشایی کندل بعد اجرا می‌شود

    risk_frac = risk_pct / 100
    fee = fee_pct / 100
    slip = slippage_pct / 100

    for i, row in df.iterrows():
        price = row["c"]
        atr = row["atr14"]
        if atr is None or np.isnan(atr) or atr <= 0:
            pending = None
            equity_curve.append(cash + (pos["notional"] * (1 + (price - pos["entry"]) / pos["entry"]) if pos else 0))
            continue

        # --- اجرای ورود معوق در بازگشایی این کندل ---
        if pending is not None and pos is None:
            entry_px = row["o"] * (1 + slip)
            sl_dist = sl_atr * pending["atr"]
            if sl_dist > 0:
                risk_amt = cash * risk_frac
                notional = min(risk_amt / (sl_dist / entry_px), cash)
                if notional >= 10:
                    cash -= notional
                    pos = {"entry": entry_px, "sl": entry_px - sl_dist,
                           "tp": entry_px + tp_atr * pending["atr"], "notional": notional,
                           "bars": 0, "peak": entry_px, "entry_idx": i}
            pending = None
            # اگر بازگشایی با گپ زیر حد ضرر بود، همان کندل خروج می‌خورد (محافظه‌کارانه)
            if pos and row["l"] <= pos["sl"]:
                exit_px = min(pos["sl"], row["o"]) * (1 - slip)
                net = (exit_px - pos["entry"]) / pos["entry"] - 2 * fee
                cash += pos["notional"] * (1 + net)
                trades.append({"entry_idx": pos["entry_idx"], "exit_idx": i,
                               "entry": pos["entry"], "exit": exit_px,
                               "reason": "SL", "pnl": pos["notional"] * net,
                               "ret": net * 100, "bars": 0})
                pos = None
                equity_curve.append(cash)
                continue

        # --- مدیریت پوزیشن باز ---
        if pos:
            pos["bars"] += 1
            pos["peak"] = max(pos["peak"], row["h"])
            if trailing_atr > 0:
                pos["sl"] = max(pos["sl"], pos["peak"] - trailing_atr * atr)
            exit_px, reason = None, ""
            if row["l"] <= pos["sl"]:
                exit_px, reason = pos["sl"] * (1 - slip), "SL"
            elif row["h"] >= pos["tp"]:
                exit_px, reason = pos["tp"] * (1 - slip), "TP"
            elif row.get("exit_long", False) or pos["bars"] >= max_holding:
                exit_px = price * (1 - slip)
                reason = "SIGNAL" if row.get("exit_long", False) else "TIME"
            if exit_px:
                net = (exit_px - pos["entry"]) / pos["entry"] - 2 * fee
                cash += pos["notional"] * (1 + net)
                trades.append({"entry_idx": pos["entry_idx"], "exit_idx": i,
                               "entry": pos["entry"], "exit": exit_px,
                               "reason": reason, "pnl": pos["notional"] * net,
                               "ret": net * 100, "bars": pos["bars"]})
                pos = None
                equity_curve.append(cash)
                continue
            equity_curve.append(cash + pos["notional"] * (1 + (price - pos["entry"]) / pos["entry"]))
            continue

        # --- ثبت سیگنال برای کندل بعد (اجرا در بازگشایی بعدی) ---
        if row.get("enter_long", False) and i + 1 < len(df):
            pending = {"atr": atr}
        equity_curve.append(cash)

    if pos:  # بستن انتهای دوره
        price = df.iloc[-1]["c"] * (1 - slip)
        net = (price - pos["entry"]) / pos["entry"] - 2 * fee
        cash += pos["notional"] * (1 + net)
        trades.append({"entry_idx": pos["entry_idx"], "exit_idx": len(df) - 1,
                       "entry": pos["entry"], "exit": price, "reason": "END",
                       "pnl": pos["notional"] * net, "ret": net * 100, "bars": pos["bars"]})

    t = pd.DataFrame(trades)
    eq = pd.Series(equity_curve if equity_curve else [cash])
    rets = eq.pct_change().dropna()
    max_dd = float(((eq - eq.cummax()) / eq.cummax()).min() * 100) if len(eq) else 0.0
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252 * 96)) if rets.std() > 0 else 0.0
    wins = t[t["pnl"] > 0] if not t.empty else t
    return {
        "final_equity": round(cash, 2),
        "total_return_pct": round((cash / 10000 - 1) * 100, 2),
        "n_trades": len(t),
        "winrate_pct": round(len(wins) / len(t) * 100, 1) if len(t) else 0.0,
        "profit_factor": round(wins["pnl"].sum() / abs(t[t["pnl"] <= 0]["pnl"].sum()), 2) if len(t) and (t["pnl"] <= 0).any() and wins["pnl"].sum() > 0 else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "avg_bars_held": round(float(t["bars"].mean()), 1) if len(t) else 0.0,
        "trades": t,
    }


def grid_search(df: pd.DataFrame, sl_opts=(1.0, 1.5, 2.0), tp_opts=(2.0, 2.5, 3.5),
                train_frac=0.7) -> pd.DataFrame:
    """بهینه‌سازی SL/TP با تفکیک آموزش/آزمون: انتخاب روی train، گزارش روی test.
    مرتب‌سازی نهایی بر اساس بازده test (جلوگیری از فریب اورفیت)."""
    n = len(df)
    cut = max(100, int(n * train_frac))
    train, test = df.iloc[:cut], df.iloc[cut:]
    rows = []
    for sl in sl_opts:
        for tp in tp_opts:
            tr = backtest(train, sl_atr=sl, tp_atr=tp)
            te = backtest(test, sl_atr=sl, tp_atr=tp)
            rows.append({"sl": sl, "tp": tp,
                         "train_ret": tr["total_return_pct"], "train_n": tr["n_trades"],
                         "train_wr": tr["winrate_pct"],
                         "total_return_pct": te["total_return_pct"],
                         "n_trades": te["n_trades"], "winrate_pct": te["winrate_pct"],
                         "profit_factor": te["profit_factor"],
                         "max_drawdown_pct": te["max_drawdown_pct"]})
    return pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
