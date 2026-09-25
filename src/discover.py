"""کشف کوین‌های جدید نوبیتکس: مقایسه لیست بازارهای صرافی با کوین‌های زیر نظر ما."""
import os
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWN_FILE = os.path.join(BASE, "known_markets.json")


def _base(sym_key: str) -> str:
    """'btc-usdt' -> 'BTC'"""
    return sym_key.split("-")[0].upper()


def all_markets(client) -> dict:
    """{BASE: {usdt: bool, irt: bool, vol_usdt: float, chg_pct: float}}"""
    out = {}
    for dst, flag in (("usdt", "usdt"), ("rls", "irt")):
        try:
            stats = client.stats(dstCurrency=dst).get("stats", {})
        except Exception:
            continue
        for k, v in stats.items():
            try:
                base = _base(k)
                e = out.setdefault(base, {"usdt": False, "irt": False,
                                          "vol_usdt": 0.0, "chg_pct": 0.0})
                e[flag] = True
                if flag == "usdt":
                    e["vol_usdt"] = float(v.get("volumeDst") or 0)
                    o, l = float(v.get("dayOpen") or 0), float(v.get("latest") or 0)
                    e["chg_pct"] = round((l / o - 1) * 100, 2) if o > 0 else 0.0
            except Exception:
                continue
    return out


def _universe(cfg: dict) -> set:
    u = set()
    for s in cfg.get("symbols", []):
        su = s.upper()
        u.add(su[:-4] if su.endswith("USDT") else su)
    for c in cfg.get("paper_coins", []):
        u.add(str(c).upper())
    return u


def candidates(cfg: dict, client, min_vol_usdt=50000, limit=50) -> list:
    """کوین‌های موجود در نوبیتکس که زیر نظر ما نیستند (مرتب به‌ترتیب حجم)."""
    uni = _universe(cfg)
    out = []
    for base, e in all_markets(client).items():
        if base in uni or not (e["usdt"] and e["irt"]):
            continue
        if e["vol_usdt"] < min_vol_usdt:
            continue
        out.append({"coin": base, "vol_usdt": round(e["vol_usdt"], 0),
                    "chg_24h": e["chg_pct"]})
    return sorted(out, key=lambda r: -r["vol_usdt"])[:limit]


def verify(client, base: str):
    """چک می‌کند کندل 15m هر دو بازار واقعاً داده می‌دهد. برمی‌گرداند (usdt_sym, irt_sym)."""
    u, i = f"{base}USDT", f"{base}IRT"
    client.klines(u, "15", 5)
    client.klines(i, "15", 5)
    return u, i


def load_baseline() -> set:
    if os.path.exists(KNOWN_FILE):
        with open(KNOWN_FILE) as f:
            return set(json.load(f))
    return set()


def save_baseline(bases: set):
    with open(KNOWN_FILE, "w") as f:
        json.dump(sorted(bases), f)


def newly_listed(client) -> list:
    """کوین‌هایی که از آخرین چک به لیست نوبیتکس اضافه شده‌اند."""
    cur = set(all_markets(client).keys())
    base = load_baseline()
    if not base:  # اولین اجرا: فقط خط مبنا را بساز، اسپم نکن
        save_baseline(cur)
        return []
    new = sorted(cur - base)
    if new:
        save_baseline(cur)
    return new
