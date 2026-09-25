"""بک‌تستر لانگ اسپات با حد ضرر/حد سود ATR، تریلینگ، کارمزد و خروج زمانی (بدون هلد)."""
import numpy as np
import pandas as pd


def backtest(df: pd.DataFrame, sl_atr=1.5, tp_atr=2.5, trailing_atr=0.0,
             fee_pct=0.1, max_holding=96, risk_pct=1.0) -> dict:
    df = df.dropna().reset_index(drop=True)
    cash, equity_curve, trades = 10000.0, [], []
    pos = None  # dict(entry, sl, tp, size, bars, peak, entry_idx)

    risk_frac = risk_pct / 100
    fee = fee_pct / 100

    for i, row in df.iterrows():
        price = row["c"]
        atr = row["atr14"]
        if atr is None or np.isnan(atr) or atr <= 0:
            continue

        # --- مدیریت پوزیشن باز ---
        if pos:
            pos["bars"] += 1
            pos["peak"] = max(pos["peak"], row["h"])
            # تریلینگ استاپ
            if trailing_atr > 0:
                trail = pos["peak"] - trailing_atr * atr
                pos["sl"] = max(pos["sl"], trail)
            exit_px, reason = None, ""
            if row["l"] <= pos["sl"]:
                exit_px, reason = pos["sl"], "SL"
            elif row["h"] >= pos["tp"]:
                exit_px, reason = pos["tp"], "TP"
            elif row.get("exit_long", False) or pos["bars"] >= max_holding:
                exit_px, reason = price, "SIGNAL" if row.get("exit_long", False) else "TIME"
            if exit_px:
                gross = (exit_px - pos["entry"]) / pos["entry"]
                net = gross - 2 * fee
                pnl = pos["notional"] * net
                cash += pos["notional"] * (1 + net)
                trades.append({"entry_idx": pos["entry_idx"], "exit_idx": i,
                               "entry": pos["entry"], "exit": exit_px,
                               "reason": reason, "pnl": pnl, "ret": net * 100,
                               "bars": pos["bars"]})
                pos = None
                equity_curve.append(cash)
                continue
            equity_curve.append(cash + pos["notional"] * (1 + (price - pos["entry"]) / pos["entry"]))
            continue

        # --- ورود ---
        if row.get("enter_long", False):
            sl_dist = sl_atr * atr
            if sl_dist <= 0:
                continue
            risk_amt = cash * risk_frac
            notional = min(risk_amt / (sl_dist / price), cash)  # سایز بر اساس ریسک
            if notional < 10:
                continue
            cash -= notional
            pos = {"entry": price, "sl": price - sl_dist,
                   "tp": price + tp_atr * atr, "notional": notional,
                   "bars": 0, "peak": price, "entry_idx": i}
        equity_curve.append(cash + (pos["notional"] * (1 + (price - pos["entry"]) / pos["entry"]) if pos else 0))

    if pos:  # بستن انتهای دوره
        price = df.iloc[-1]["c"]
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


def grid_search(df: pd.DataFrame, sl_opts=(1.0, 1.5, 2.0), tp_opts=(2.0, 2.5, 3.5)) -> pd.DataFrame:
    """بهینه‌سازی کوچک SL/TP برای هر کوین."""
    rows = []
    for sl in sl_opts:
        for tp in tp_opts:
            r = backtest(df, sl_atr=sl, tp_atr=tp)
            rows.append({"sl": sl, "tp": tp, **{k: v for k, v in r.items() if k != "trades"}})
    return pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
