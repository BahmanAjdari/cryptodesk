"""اندیکاتورهای تکنیکال — پیاده‌سازی خالص با pandas/numpy (بدون TA-Lib)."""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    m = ema(close, fast) - ema(close, slow)
    sig = m.ewm(span=signal, adjust=False).mean()
    return m, sig, m - sig


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["h"], df["l"], df["c"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def bollinger(close: pd.Series, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n).std()
    return mid + k * sd, mid, mid - k * sd


def stochastic(df: pd.DataFrame, k=14, d=3):
    low = df["l"].rolling(k).min()
    high = df["h"].rolling(k).max()
    kline = 100 * (df["c"] - low) / (high - low).replace(0, np.nan)
    return kline, kline.rolling(d).mean()


def adx(df: pd.DataFrame, n=14) -> pd.Series:
    h, l, c = df["h"], df["l"], df["c"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr_s = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def donchian(df: pd.DataFrame, n=20):
    return df["h"].rolling(n).max(), df["l"].rolling(n).min()


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """همه اندیکاتورهای لازم را به دیتافریم اضافه می‌کند."""
    df = df.copy()
    c = df["c"]
    df["ema9"] = ema(c, 9)
    df["ema21"] = ema(c, 21)
    df["ema50"] = ema(c, 50)
    df["ema200"] = ema(c, 200)
    df["rsi14"] = rsi(c, 14)
    m, sig, hist = macd(c)
    df["macd"], df["macd_sig"], df["macd_hist"] = m, sig, hist
    df["atr14"] = atr(df, 14)
    bb_u, bb_m, bb_l = bollinger(c)
    df["bb_u"], df["bb_m"], df["bb_l"] = bb_u, bb_m, bb_l
    df["bb_pct"] = (c - bb_l) / (bb_u - bb_l).replace(0, np.nan)
    sk, sd = stochastic(df)
    df["stoch_k"], df["stoch_d"] = sk, sd
    df["adx14"] = adx(df, 14)
    dc_u, dc_l = donchian(df, 20)
    df["dc_u"], df["dc_l"] = dc_u, dc_l
    df["vol_sma20"] = df["v"].rolling(20).mean()
    df["chg_pct"] = c.pct_change() * 100
    return df
