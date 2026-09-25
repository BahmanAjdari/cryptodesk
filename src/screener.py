"""اسکرینر: رتبه‌بندی کوین‌ها با ترکیب بک‌تست + سیگنال لحظه‌ای + حجم."""
import pandas as pd
from .strategies import apply_all
from .backtest import backtest


def screen(symbols_data: dict, cfg: dict, min_score=None, rs_window=12) -> pd.DataFrame:
    """symbols_data: {symbol: df_raw}. خروجی: جدول رتبه‌بندی‌شده.
    min_score: آستانه امتیاز ورود (پیش‌فرض از config).
    rs_window: پنجره قدرت نسبی به BTC (کندل)."""
    ms = cfg["screener"]["min_signal_score"] if min_score is None else min_score
    btc_key = next((k for k in symbols_data if k.upper().startswith("BTC")), None)
    btc_ret = None
    if btc_key is not None:
        try:
            bc = symbols_data[btc_key]["c"].astype(float)
            btc_ret = float(bc.iloc[-1] / bc.iloc[-rs_window] - 1)
        except Exception:
            btc_ret = None
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
            quote = "IRT" if sym.upper().endswith(("IRT", "RLS")) else "USDT"
            day_vol = float(raw.tail(96)["v"].sum() * raw.tail(1)["c"].iloc[0])  # به ارز همان بازار
            try:
                cc = raw["c"].astype(float)
                rs = round((float(cc.iloc[-1] / cc.iloc[-rs_window] - 1) - btc_ret) * 100, 2) \
                    if btc_ret is not None and not sym.upper().startswith("BTC") else 0.0
            except Exception:
                rs = 0.0
            rows.append({
                "symbol": sym,
                "quote": quote,
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
                "rs_vs_btc": rs,
                "day_vol": round(day_vol, 0),
            })
        except Exception as e:
            rows.append({"symbol": sym, "error": str(e)})
    out = pd.DataFrame(rows)
    if "day_vol" in out.columns:
        # آستانه حجم بر حسب ارز همان بازار (تومان جدا از تتر)
        def _pass(r):
            if pd.isna(r.get("day_vol")):
                return False
            thr = cfg["screener"].get("min_day_volume_irt", 10_000_000_000) \
                if r.get("quote") == "IRT" else cfg["screener"]["min_day_volume_usdt"]
            return r["day_vol"] >= thr
        out = out[out.apply(_pass, axis=1)]
    # امتیاز نهایی: ۵۰٪ بک‌تست + ۳۰٪ سیگنال لحظه‌ای + ۲۰٪ وین‌ریت + امتیاز قدرت نسبی به BTC
    if not out.empty and "ret_pct" in out.columns:
        out["rank_score"] = ((out["ret_pct"].clip(-20, 50) + 20) * 0.5 + out["score_now"] * 10 * 0.3
                             + out["winrate"] * 0.2 + out["rs_vs_btc"].clip(-3, 3) * 2)
        out = out.sort_values("rank_score", ascending=False).reset_index(drop=True)
    return out
