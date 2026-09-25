"""تحلیل سنتیمنت/اخبار + تشخیص رژیم بازار.

منابع:
1) Fear & Greed (Alternative.me — رایگان، بدون کلید)
2) CryptoPanic (اختیاری، اگر توکن بدهی)
3) رژیم تکنیکال: ADX + EMA200 + روند BTC
"""
import re
import requests
import pandas as pd

NEG_WORDS = ["hack", "exploit", "lawsuit", "sec", "ban", "crash", "scam", "attack",
             "هک", "کلاهبرداری", "ممنوع", "سقوط", "شکایت"]
POS_WORDS = ["etf", "approval", "adoption", "partnership", "upgrade", "record",
             "تایید", "رشد", "رکورد", "همکاری"]


def fear_greed(url="https://api.alternative.me/fng/?limit=7&format=json"):
    try:
        j = requests.get(url, timeout=15).json()["data"]
        cur = j[0]
        vals = [int(x["value"]) for x in j]
        return {"value": int(cur["value"]), "label": cur["value_classification"],
                "trend": sum(vals) / len(vals),
                "raw": j}
    except Exception as e:
        return {"value": 50, "label": f"unknown ({e})", "trend": 50, "raw": []}


def cryptopanic_sentiment(base_url, token):
    """امتیاز ساده خبری: +1 مثبت / -1 منفی بر اساس تیترها."""
    if not token:
        return {"score": 0, "n": 0, "note": "no token — skipped"}
    try:
        j = requests.get(base_url.format(token=token), timeout=15).json()
        titles = [p.get("title", "") for p in j.get("results", [])]
        score, details = 0, []
        for t in titles:
            tl = t.lower()
            s = sum(1 for w in POS_WORDS if w in tl) - sum(2 for w in NEG_WORDS if w in tl)
            score += s
            if s != 0:
                details.append((s, t))
        return {"score": score, "n": len(titles), "details": details[:10]}
    except Exception as e:
        return {"score": 0, "n": 0, "note": str(e)}


def market_regime(btc_df: pd.DataFrame, adx_th=20) -> dict:
    """رژیم BTC: bull / bear / range — فیلتر اصلی ورود به آلت‌کوین‌ها."""
    last = btc_df.iloc[-1]
    up = last["c"] > last["ema50"] > last["ema200"]
    down = last["c"] < last["ema50"]
    adx = float(last["adx14"])
    if up and adx > adx_th:
        regime = "bull"
    elif down and adx > adx_th:
        regime = "bear"
    else:
        regime = "range"
    return {"regime": regime, "adx": round(adx, 1),
            "above_ema200": bool(last["c"] > last["ema200"])}


def trade_gate(cfg: dict, fg: dict, news: dict, regime: dict) -> dict:
    """تصمیم نهایی: آیا اجازه ورود هست؟"""
    reasons = []
    allow = True
    v = fg["value"]
    if v >= 75 and cfg["regime"]["block_on_extreme_greed_bear"]:
        reasons.append(f"طمع شدید ({v}) — ورود جدید ممنوع")
        allow = False
    if v <= 15 and cfg["regime"]["block_on_extreme_fear_bull"]:
        reasons.append(f"ترس شدید ({v}) — خرید ممنوع")
        allow = False
    if cfg["regime"]["block_trading_if_negative_news"] and news.get("score", 0) <= -3:
        reasons.append(f"اخبار منفی ({news['score']}) — معامله ممنوع")
        allow = False
    if cfg["regime"]["btc_trend_filter"] and regime.get("regime") == "bear":
        reasons.append("روند BTC نزولی — ورود به آلت‌کوین ممنوع")
        allow = False
    if not reasons:
        reasons.append(f"مجاز | رژیم: {regime.get('regime')} | F&G: {v} ({fg.get('label')}) | news: {news.get('score', 0)}")
    return {"allow": allow, "reasons": reasons, "fear_greed": fg,
            "news": news, "regime": regime}
