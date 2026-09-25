"""۴ استراتژی کوتاه‌مدت (اسکالپ/اینترادِی، بدون هلد) + سیگنال ترکیبی.

هر استراتژی: signal ∈ {-1, 0, +1} و score ∈ [0, 2] برای امتیازدهی اسکرینر.
اسپات نوبیتکس شورت ندارد، پس سیگنال -1 یعنی «خروج / عدم ورود».
"""
import pandas as pd
from .indicators import add_all


def strat_ema_macd_trend(df: pd.DataFrame) -> pd.DataFrame:
    """۱) روند کوتاه‌مدت: EMA9>EMA21 + MACD_hist>0 + قیمت بالای EMA50 + ADX>20"""
    df = df.copy()
    long = (df["ema9"] > df["ema21"]) & (df["macd_hist"] > 0) & (df["c"] > df["ema50"]) & (df["adx14"] > 20)
    short = (df["ema9"] < df["ema21"]) & (df["macd_hist"] < 0)
    df["sig_trend"] = 0
    df.loc[long, "sig_trend"] = 1
    df.loc[short, "sig_trend"] = -1
    df["score_trend"] = 0.0
    df.loc[long, "score_trend"] = 1.0 + (df["adx14"] / 50).clip(0, 1)
    df.loc[short, "score_trend"] = 1.0
    # خروج: کراس معکوس EMA یا برگشت MACD
    df["exit_trend"] = (df["ema9"] < df["ema21"]) | (df["macd_hist"] < 0)
    return df


def strat_rsi_meanrev(df: pd.DataFrame) -> pd.DataFrame:
    """۲) میانگین‌بازگشتی: RSI<30 + برخورد به باند پایین بولینگر + استوکاستیک صعودی"""
    df = df.copy()
    long = (df["rsi14"] < 32) & (df["c"] <= df["bb_l"] * 1.005) & (df["stoch_k"] > df["stoch_d"])
    overbought = (df["rsi14"] > 68) | (df["c"] >= df["bb_u"] * 0.995)
    df["sig_mr"] = 0
    df.loc[long, "sig_mr"] = 1
    df.loc[overbought, "sig_mr"] = -1
    df["score_mr"] = 0.0
    df.loc[long, "score_mr"] = (32 - df["rsi14"]).clip(0, 15) / 15 * 2
    df.loc[overbought, "score_mr"] = 1.0
    df["exit_mr"] = (df["rsi14"] > 55) | (df["c"] >= df["bb_m"])
    return df


def strat_breakout(df: pd.DataFrame) -> pd.DataFrame:
    """۳) بریک‌اوت دانچیان۲۰ + حجم بالای میانگین + ADX>20 (مخصوص بازار تند کوتاه‌مدت)"""
    df = df.copy()
    brk = (df["c"] > df["dc_u"].shift(1)) & (df["v"] > df["vol_sma20"] * 1.3) & (df["adx14"] > 20)
    fail = df["c"] < df["bb_m"]
    df["sig_brk"] = 0
    df.loc[brk, "sig_brk"] = 1
    df.loc[fail, "sig_brk"] = -1
    df["score_brk"] = 0.0
    df.loc[brk, "score_brk"] = 1.0 + (df["v"] / df["vol_sma20"] / 3).clip(0, 1)
    df["exit_brk"] = fail
    return df


def strat_boll_squeeze(df: pd.DataFrame) -> pd.DataFrame:
    """۴) اسکوییز بولینگر: پهنای باند فشرده + خروج از باند + RSI تایید"""
    df = df.copy()
    width = (df["bb_u"] - df["bb_l"]) / df["bb_m"]
    squeeze = width < width.rolling(50).quantile(0.25)
    sqz_armed = squeeze.shift(1).eq(True)  # بدون هشدار fillna روی bool
    long = sqz_armed & (df["c"] > df["bb_u"]) & (df["rsi14"] > 50) & (df["rsi14"] < 75)
    exit_ = (df["c"] < df["bb_m"]) | (df["rsi14"] > 78)
    df["sig_sqz"] = 0
    df.loc[long, "sig_sqz"] = 1
    df.loc[exit_, "sig_sqz"] = -1
    df["score_sqz"] = 0.0
    df.loc[long, "score_sqz"] = 1.5
    df["exit_sqz"] = exit_
    return df


STRATS = {
    "trend": strat_ema_macd_trend,
    "meanrev": strat_rsi_meanrev,
    "breakout": strat_breakout,
    "squeeze": strat_boll_squeeze,
}


def apply_all(df: pd.DataFrame, min_score: float = 2.0) -> pd.DataFrame:
    df = add_all(df)
    for fn in STRATS.values():
        df = fn(df)
    sig_cols = ["sig_trend", "sig_mr", "sig_brk", "sig_sqz"]
    score_cols = ["score_trend", "score_mr", "score_brk", "score_sqz"]
    df["signal_sum"] = df[sig_cols].sum(axis=1)
    # امتیاز فقط از استراتژی‌های موافق (سیگنال منفی امتیاز ندارد)
    pos_mask = df[sig_cols].gt(0)
    df["score_total"] = df[score_cols].where(pos_mask.values).sum(axis=1)
    n_pos = pos_mask.sum(axis=1)
    # ورود: اجماع ≥۲ استراتژی موافق + آستانه امتیاز + RSI اشباع‌خرید نباشد
    df["enter_long"] = (n_pos >= 2) & (df["score_total"] >= min_score) & (df["rsi14"] < 72)
    # سیگنال خروج: اجماع منفی (حد ضرر/حد سود/زمان در بک‌تستر جدا اعمال می‌شود؛
    # خروج‌های تک‌استراتژی عجولانه‌اند و فقط برای اطلاع نگه داشته شده‌اند)
    df["exit_long"] = df["signal_sum"] <= -2
    return df
