"""موتور معامله: اسکن → گیت اخبار/رژیم → ورود مارکت → خروج OCO (حد سود + حد ضرر).

- پیش‌فرض dry_run=True: سفارش واقعی ثبت نمی‌کند، فقط لاگ.
- برای لایو: NOBITEX_TOKEN در .env + dry_run: False در config.
- اسپات: فقط لانگ؛ خروج با OCO فروش (TP + SL هم‌زمان). هلد ممنوع (خروج زمانی).
"""
import os
import time
import uuid
import yaml
import pandas as pd

from .nobitex_client import NobitexClient
from .strategies import apply_all
from .screener import screen
from . import news as newsmod


def load_cfg(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def split_symbol(sym: str):
    s = sym.upper()
    for q in ("USDT", "IRT", "RLS"):
        if s.endswith(q):
            base = s[:-len(q)]
            dst = "rls" if q == "IRT" else q.lower()
            return base.lower(), dst
    return s.lower(), "usdt"


class Trader:
    def __init__(self, cfg, client: NobitexClient):
        self.cfg = cfg
        self.client = client
        self.dry = cfg["execution"].get("dry_run", True)
        self.positions = {}  # symbol -> {entry, sl, tp, amount, oco_ids, bars}
        self.daily_pnl = 0.0
        self.day = pd.Timestamp.utcnow().date()

    # ---------- data ----------
    def fetch_all(self):
        data = {}
        tf = self.cfg["timeframe"]
        n = self.cfg["candles"]
        for sym in self.cfg["symbols"]:
            try:
                data[sym] = self.client.klines(sym, tf, n)
                time.sleep(0.3)
            except Exception as e:
                print(f"[!] {sym}: {e}")
        return data

    def gate(self, data):
        ncfg = self.cfg["news"]
        fg = newsmod.fear_greed(ncfg["fear_greed_url"])
        ns = newsmod.cryptopanic_sentiment(ncfg["cryptopanic_url"], ncfg.get("cryptopanic_token", ""))
        reg = {"regime": "range"}
        if "BTCUSDT" in data:
            try:
                reg = newsmod.market_regime(apply_all(data["BTCUSDT"]),
                                            self.cfg["regime"]["adx_trend_threshold"])
            except Exception as e:
                reg = {"regime": "range", "note": str(e)}
        g = newsmod.trade_gate(self.cfg, fg, ns, reg)
        print("GATE:", " | ".join(g["reasons"]))
        return g

    # ---------- sizing ----------
    def size_amount(self, price, atr, balance_quote):
        r = self.cfg["risk"]
        risk_amt = balance_quote * r["trade_risk_pct"] / 100
        sl_dist = r["sl_atr_mult"] * atr
        if sl_dist <= 0 or price <= 0:
            return 0.0
        notional = min(risk_amt / (sl_dist / price), balance_quote / self.cfg["risk"]["max_open_positions"])
        return round(notional / price, 8)

    def balance_quote(self):
        if self.dry:
            return 1000.0  # بالانس مجازی پیپر
        try:
            w = self.client.wallets()
            q = self.cfg["execution"].get("quote_asset", "USDT").lower()
            if isinstance(w, dict):
                for row in w.get("wallets", w.get("balances", [])):
                    if str(row.get("currency", "")).lower() in (q, "rls" if q == "rls" else q):
                        return float(row.get("balance", 0))
            return 0.0
        except Exception as e:
            print("[!] wallets:", e)
            return 0.0

    # ---------- orders ----------
    def enter(self, symbol, price, atr):
        src, dst = split_symbol(symbol)
        bal = self.balance_quote()
        amt = self.size_amount(price, atr, bal)
        if amt <= 0:
            print(f"[-] {symbol}: سایز صفر"); return
        r = self.cfg["risk"]
        sl = price - r["sl_atr_mult"] * atr
        tp = price + r["tp_atr_mult"] * atr
        cid = f"bot-{uuid.uuid4().hex[:8]}"
        print(f"[ENTER] {symbol} price={price:.4f} amt={amt} SL={sl:.4f} TP={tp:.4f} dry={self.dry}")
        if self.dry:
            self.positions[symbol] = {"entry": price, "sl": sl, "tp": tp, "amount": amt, "bars": 0}
            return
        try:
            o = self.client.buy_market(src, dst, amt, price_hint=price)
            print("  order:", o)
            # خروج OCO: فروش هم‌زمان TP + SL
            oco = self.client.oco_exit(src, dst, amt, f"{tp:.8f}", f"{sl:.8f}",
                                       f"{sl * 0.999:.8f}", client_order_id=cid)
            print("  oco:", oco)
            self.positions[symbol] = {"entry": price, "sl": sl, "tp": tp,
                                      "amount": amt, "bars": 0, "oco": oco}
        except Exception as e:
            print(f"[!] enter failed {symbol}: {e}")

    def manage(self, symbol, row):
        """بررسی خروج برای پوزیشن باز (حالت dry_run؛ در لایو OCO صرافی فعال است + خروج زمانی)."""
        if symbol not in self.positions:
            return
        p = self.positions[symbol]
        p["bars"] += 1
        price = row["c"]
        # تریلینگ (فقط اگر در کانفیگ روشن باشد)
        tmult = self.cfg["risk"]["trailing_atr_mult"]
        if tmult > 0 and not pd.isna(row["atr14"]):
            # تریل بر اساس سقف از ورود
            p["peak"] = max(p.get("peak", p["entry"]), row["h"])
            p["sl"] = max(p["sl"], p["peak"] - tmult * row["atr14"])
        reason = None
        if row["l"] <= p["sl"]:
            reason = "SL"
        elif row["h"] >= p["tp"]:
            reason = "TP"
        elif row.get("exit_long", False):
            reason = "SIGNAL"
        elif p["bars"] >= self.cfg["risk"]["max_holding_candles"]:
            reason = "TIME"
        if reason:
            pnl = (price - p["entry"]) / p["entry"] * 100
            print(f"[EXIT:{reason}] {symbol} @ {price:.4f} pnl={pnl:.2f}% bars={p['bars']}")
            if not self.dry:
                try:
                    src, dst = split_symbol(symbol)
                    print(self.client.sell_market(src, dst, p["amount"]))
                except Exception as e:
                    print("[!] exit failed:", e)
            del self.positions[symbol]

    # ---------- main loop ----------
    def scan_once(self):
        # ریست روزانه
        today = pd.Timestamp.utcnow().date()
        if today != self.day:
            self.day, self.daily_pnl = today, 0.0
        data = self.fetch_all()
        if not data:
            print("[!] داده‌ای گرفته نشد"); return
        g = self.gate(data)
        # مدیریت پوزیشن‌های باز
        for sym, raw in data.items():
            if sym in self.positions:
                try:
                    self.manage(sym, apply_all(raw).iloc[-1])
                except Exception as e:
                    print("[!] manage:", e)
        if not g["allow"]:
            print("[BLOCK] ورود جدید مجاز نیست"); return
        if len(self.positions) >= self.cfg["risk"]["max_open_positions"]:
            print("[SKIP] سقف پوزیشن باز"); return
        table = screen(data, self.cfg)
        print(table.to_string() if not table.empty else "(empty)")
        for _, r in table.iterrows():
            sym = r["symbol"]
            if sym in self.positions or not r.get("enter_now", False):
                continue
            if r["score_now"] < self.cfg["screener"]["min_signal_score"]:
                continue
            raw = data[sym]
            last = apply_all(raw).iloc[-1]
            if pd.isna(last["atr14"]) or last["atr14"] <= 0:
                continue
            self.enter(sym, float(last["c"]), float(last["atr14"]))
            if len(self.positions) >= self.cfg["risk"]["max_open_positions"]:
                break

    def run(self):
        print(f"=== Nobitex bot started (dry_run={self.dry}) ===")
        while True:
            try:
                self.scan_once()
            except Exception as e:
                print("[!] loop error:", e)
            time.sleep(self.cfg["execution"]["poll_seconds"])
