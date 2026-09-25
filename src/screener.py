"""اسکرینر: رتبه‌بندی کوین‌ها با ترکیب بک‌تست + سیگنال لحظه‌ای + حجم."""
import pandas as pd
from .strategies import apply_all
from .backtest import backtest


def screen(symbols_data: dict, cfg: dict, min_score=None) -> pd.DataFrame:
    """symbols_data: {symbol: df_raw}. خروجی: جدول رتبه‌بندی‌شده.
    min_score: آستانه امتیاز ورود (پیش‌فرض از config)."""
    ms = cfg["screener"]["min_signal_score"] if min_score is None else min_score
    rows = []
    for sym, raw in symbols_data.items():
        try:
            df = apply_all(raw, min_score=ms)
            bt = backtest(df, sl_atr=cfg["risk"]["sl_atr_mult"],
                          tp_atr=cfg["risk"]["tp_atr_mult"],
                          trailing_atr=cfg["risk"]["trailing_atr_mult"],
                          fee_pct=cfg["risk"]["fee_pct"],
                          max_holding=cfg["risk"]["max_holding_candles"])
            last = df.iloc[-1]
            day_vol = float(raw.tail(96)["v"].sum() * raw.tail(1)["c"].iloc[0])  # تخمین حجم دلاری
            rows.append({
                "symbol": sym,
                "last_close": round(float(last["c"]), 4),
                "score_now": round(float(last["score_total"]), 2),
                "signal_now": int(last["signal_sum"]),
                "enter_now": bool(last["enter_long"]),
                "rsi": round(float(last["rsi14"]), 1),
                "adx": round(float(last["adx14"]), 1),
                "ret_pct": bt["total_return_pct"],
                "winrate": bt["winrate_pct"],
                "pf": bt["profit_factor"],
                "maxdd": bt["max_drawdown_pct"],
                "n_trades": bt["n_trades"],
                "day_vol_usdt": round(day_vol, 0),
            })
        except Exception as e:
            rows.append({"symbol": sym, "error": str(e)})
    out = pd.DataFrame(rows)
    if "day_vol_usdt" in out.columns:
        out = out[out["day_vol_usdt"] >= cfg["screener"]["min_day_volume_usdt"]]
    # امتیاز نهایی: ۵۰٪ بک‌تست + ۳۰٪ سیگنال لحظه‌ای + ۲۰٪ وین‌ریت
    if not out.empty and "ret_pct" in out.columns:
        out["rank_score"] = (out["ret_pct"].clip(-20, 50) + 20) * 0.5 + out["score_now"] * 10 * 0.3 + out["winrate"] * 0.2
        out = out.sort_values("rank_score", ascending=False).reset_index(drop=True)
    return out
