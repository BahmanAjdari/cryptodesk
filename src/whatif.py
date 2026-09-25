"""شبیه‌ساز «اگه وارد می‌شدم؟» — سود/ضرر فرضی از N ساعت پیش تا الان با قیمت واقعی نوبیتکس.

دو حالت:
- hold: خرید در N ساعت پیش و نگهداری تا الان
- strategy: ورود در N ساعت پیش ولی با مدیریت بات (حد ضرر/حد سود ATR + خروج سیگنالی)؛
  اگر حد ضرر بخورد، پول نقد می‌ماند تا الان.
"""
import pandas as pd


def _slice_from_hours_ago(df: pd.DataFrame, hours_ago: float) -> pd.DataFrame:
    """برش کندل‌ها از نزدیک‌ترین کندل به (الان - hours_ago) تا آخر."""
    end = df["time"].max()
    target = end - pd.Timedelta(hours=hours_ago)
    idx = (df["time"] - target).abs().idxmin()
    return df.loc[idx:].reset_index(drop=True)


def simulate_hold(df: pd.DataFrame, hours_ago: float, amount: float, fee_pct=0.1) -> dict:
    sl = _slice_from_hours_ago(df, hours_ago)
    entry, now = float(sl.iloc[0]["c"]), float(sl.iloc[-1]["c"])
    fee = fee_pct / 100
    bought = (amount * (1 - fee)) / entry
    final = bought * now * (1 - fee)
    pnl = final - amount
    return {
        "mode": "hold", "entry_price": entry, "now_price": now,
        "entry_time": sl.iloc[0]["time"], "n_candles": len(sl),
        "final_value": round(final, 2), "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / amount * 100, 2),
        "exit_reason": "HOLD تا الان", "exit_time": sl.iloc[-1]["time"],
        "slice": sl,
    }


def simulate_strategy(df: pd.DataFrame, hours_ago: float, amount: float,
                      sl_atr=1.5, tp_atr=2.5, fee_pct=0.1) -> dict:
    """نیازمند ستون‌های apply_all شده (atr14, exit_long)."""
    sl = _slice_from_hours_ago(df, hours_ago).reset_index(drop=True)
    fee = fee_pct / 100
    entry_row = sl.iloc[0]
    entry, atr = float(entry_row["c"]), float(entry_row["atr14"])
    if not (atr > 0):
        # بدون ATR: مثل هلد
        return simulate_hold(df, hours_ago, amount, fee_pct)
    stop = entry - sl_atr * atr
    take = entry + tp_atr * atr
    notional = amount * (1 - fee)
    exit_px, reason, exit_time = float(sl.iloc[-1]["c"]), "HOLD تا الان", sl.iloc[-1]["time"]
    for _, row in sl.iloc[1:].iterrows():
        if row["l"] <= stop:
            exit_px, reason, exit_time = stop, "SL (حد ضرر)", row["time"]
            break
        if row["h"] >= take:
            exit_px, reason, exit_time = take, "TP (حد سود)", row["time"]
            break
        if row.get("exit_long", False):
            exit_px, reason, exit_time = float(row["c"]), "SIGNAL (سیگنال خروج)", row["time"]
            break
    final = notional / entry * exit_px * (1 - fee)
    pnl = final - amount
    return {
        "mode": "strategy", "entry_price": entry, "now_price": float(sl.iloc[-1]["c"]),
        "entry_time": sl.iloc[0]["time"], "n_candles": len(sl),
        "final_value": round(final, 2), "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / amount * 100, 2),
        "exit_reason": reason, "exit_time": exit_time,
        "stop": stop, "take": take,
        "slice": sl,
    }


def simulate(df: pd.DataFrame, hours_ago: float, amount: float, mode="hold",
             sl_atr=1.5, tp_atr=2.5, fee_pct=0.1) -> dict:
    if mode == "strategy":
        return simulate_strategy(df, hours_ago, amount, sl_atr, tp_atr, fee_pct)
    return simulate_hold(df, hours_ago, amount, fee_pct)
