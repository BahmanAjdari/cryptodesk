"""موتور معامله: اسکن → گیت اخبار/رژیم → ورود مارکت → خروج OCO (حد سود + حد ضرر).

- پیش‌فرض dry_run=True: سفارش واقعی ثبت نمی‌کند، فقط لاگ.
- برای لایو: NOBITEX_TOKEN در .env + dry_run: False در config.
- اسپات: فقط لانگ؛ خروج با OCO فروش (TP + SL هم‌زمان). هلد ممنوع (خروج زمانی).
"""
import json
import os
import time
import uuid
import yaml
import pandas as pd

from .nobitex_client import NobitexClient
from .strategies import apply_all
from .screener import screen
from . import news as newsmod

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "trader_state.json")


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
        self.positions = {}  # symbol -> {entry, sl, tp, amount, buy_id, oco_ids, bars}
        self.daily_pnl = 0.0
        self.day = pd.Timestamp.utcnow().date()
        self.allow_new = True
        self._load_state()
        if not self.dry:
            self.allow_new = self.reconcile()

    # ---------- persistent state ----------
    def _save_state(self):
        if self.dry:
            return
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self.positions, f, default=str)
        except Exception as e:
            print(f"[!] save trader state: {e}")

    def _load_state(self):
        if self.dry or not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                self.positions = json.load(f)
            print(f"[i] loaded {len(self.positions)} stored live positions")
        except Exception as e:
            print(f"[!] load trader state: {e}")
            self.positions = {}

    def reconcile(self) -> bool:
        """تطبیق پوزیشن‌های ذخیره‌شده با سفارش‌های باز صرافی پس از راه‌اندازی مجدد.
        برمی‌گرداند آیا ورود جدید مجاز است."""
        try:
            open_orders = self.client.orders_list(status="open").get("orders", [])
        except Exception as e:
            print(f"[!] reconcile: cannot reach exchange ({e}) — ورود جدید متوقف شد")
            return False
        open_ids = set()
        for o in open_orders:
            open_ids.add(str(o.get("id")))
            if o.get("clientOrderId"):
                open_ids.add(str(o.get("clientOrderId")))
        for sym in list(self.positions):
            p = self.positions[sym]
            oco_ids = [str(i) for i in p.get("oco_ids", []) if i]
            buy_id = str(p.get("buy_id") or "")
            # هیچ‌کدام از سفارش‌های این پوزیشن در صرافی باز نیستند → احتمالاً بسته/لغو شده
            alive = any(i in open_ids for i in oco_ids + [buy_id]) if (oco_ids or buy_id) else False
            if not alive and (oco_ids or buy_id):
                print(f"[!] reconcile: {sym} در صرافی باز نیست (احتمالاً OCO پر شده) — از پیگیری خارج شد")
                del self.positions[sym]
        self._save_state()
        return True

    def _wait_fill(self, order_id=None, client_order_id=None, timeout=30) -> dict:
        """منتظر پر شدن سفارش می‌ماند؛ وضعیت نهایی را برمی‌گرداند."""
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            try:
                r = self.client.order_status(order_id=order_id, client_order_id=client_order_id)
                if r.get("status") == "ok":
                    last = r["order"]
                    if last.get("status") == "Done":
                        return last
                    if float(last.get("matchedAmount") or 0) > 0 and last.get("status") == "Active":
                        time.sleep(3)
                        continue
                    return last
                return last
            except Exception as e:
                print(f"[!] order status: {e}")
            time.sleep(3)
        return last

    @staticmethod
    def _filled(order: dict) -> tuple:
        """(مقدار پرشده، میانگین قیمت)"""
        try:
            amt = float(order.get("matchedAmount") or 0)
        except Exception:
            amt = 0.0
        try:
            px = float(order.get("averagePrice") or 0) or float(order.get("price") or 0)
        except Exception:
            px = 0.0
        return amt, px

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
            buy_cid = f"bot-buy-{uuid.uuid4().hex[:8]}"
            o = self.client.order_add(side="buy", src=src, dst=dst, amount=amt,
                                      price=price, execution="market",
                                      client_order_id=buy_cid)
            if o.get("status") != "ok" or "order" not in o:
                print(f"[!] buy rejected {symbol}: {o}")
                return
            buy = self._wait_fill(order_id=o["order"].get("id"), client_order_id=buy_cid)
            filled, avg = self._filled(buy)
            if filled <= 0:
                print(f"[!] buy {symbol} پر نشد — OCO ثبت نمی‌شود")
                try:
                    self.client.order_cancel(order_id=o["order"].get("id"))
                except Exception:
                    pass
                return
            if filled < amt * 0.999:
                print(f"[!] buy {symbol} جزئی پر شد ({filled}/{amt}) — OCO با مقدار واقعی")
            # خروج OCO با مقدار پرشده واقعی و قیمت میانگین واقعی
            oco = self.client.oco_exit(src, dst, f"{filled:.8f}", f"{tp:.8f}", f"{sl:.8f}",
                                       f"{sl * 0.999:.8f}", client_order_id=cid)
            print("  oco:", oco)
            oco_ids = [x.get("id") for x in oco.get("orders", [])] if oco.get("status") == "ok" else []
            if not oco_ids:
                print(f"[!] OCO {symbol} ثبت نشد — با مارکت خارج شو! {oco}")
                try:
                    print(self.client.sell_market(src, dst, f"{filled:.8f}"))
                except Exception as e:
                    print(f"[!] emergency exit failed: {e}")
                return
            self.positions[symbol] = {"entry": avg or price, "sl": sl, "tp": tp,
                                      "amount": filled, "bars": 0,
                                      "buy_id": o["order"].get("id"), "oco_ids": oco_ids}
            self._save_state()
        except Exception as e:
            print(f"[!] enter failed {symbol}: {e}")

    def manage(self, symbol, row):
        """بررسی خروج. در لایو اول OCO صرافی استعلام می‌شود (TP/SL صرافی) و
        برای خروج دستی اول OCO لغو بعد مارکت فروخته می‌شود."""
        if symbol not in self.positions:
            return
        p = self.positions[symbol]
        # --- مسیر لایو: OCO صرافی حرف اول را می‌زند ---
        if not self.dry and p.get("oco_ids"):
            done_leg = self._check_oco(symbol, p)
            if done_leg:
                return  # صرافی خودش بست؛ ثبت و حذف انجام شد
        p["bars"] += 1
        price = row["c"]
        # تریلینگ (فقط اگر در کانفیگ روشن باشد)
        tmult = self.cfg["risk"]["trailing_atr_mult"]
        if tmult > 0 and not pd.isna(row["atr14"]):
            # تریل بر اساس سقف از ورود
            p["peak"] = max(p.get("peak", p["entry"]), row["h"])
            p["sl"] = max(p["sl"], p["peak"] - tmult * row["atr14"])
            self._save_state()
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
                self._live_exit(symbol, p, reason)
            else:
                del self.positions[symbol]

    def _check_oco(self, symbol, p) -> bool:
        """استعلام پایه‌های OCO؛ اگر یکی Done شده، پوزیشن را می‌بندد. True یعنی بسته شد."""
        for oid in p.get("oco_ids", []):
            try:
                r = self.client.order_status(order_id=int(oid))
            except Exception as e:
                print(f"[!] oco status {oid}: {e}")
                continue
            if r.get("status") != "ok":
                continue
            o = r["order"]
            if o.get("status") == "Done":
                filled, avg = self._filled(o)
                leg = o.get("execution", "")
                reason = "TP" if "Limit" in str(leg) and "Stop" not in str(leg) else "SL"
                print(f"[EXIT:{reason}@exchange] {symbol} @ {avg} amt={filled}")
                del self.positions[symbol]
                self._save_state()
                return True
        return False

    def _live_exit(self, symbol, p, reason):
        """خروج دستی لایو: اول لغو OCO، بعد فروش مارکت به مقدار واقعی."""
        src, dst = split_symbol(symbol)
        for oid in p.get("oco_ids", []):
            try:
                print(self.client.order_cancel(order_id=int(oid)))
            except Exception as e:
                print(f"[!] cancel {oid}: {e}")
        try:
            o = self.client.sell_market(src, dst, p["amount"])
            print(o)
            if o.get("status") == "ok" and "order" in o:
                s = self._wait_fill(order_id=o["order"].get("id"))
                filled, avg = self._filled(s)
                print(f"[EXIT:{reason}] {symbol} sold {filled} @ {avg}")
        except Exception as e:
            print(f"[!] exit failed {symbol}: {e} — پوزیشن نگه داشته شد")
            return
        del self.positions[symbol]
        self._save_state()

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
        if not self.allow_new:
            print("[SKIP] تطبیق با صرافی ناموفق بود — ورود جدید مجاز نیست"); return
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
