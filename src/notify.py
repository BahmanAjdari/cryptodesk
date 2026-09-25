"""اطلاع‌رسانی به گروه بله (Bale) — API مشابه تلگرام: https://tapi.bale.ai/bot<TOKEN>/sendMessage"""
import os
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def get_notifier():
    """اگر توکن و آیدی گروه ست باشد، Notifier برمی‌گرداند، وگرنه None."""
    token = os.getenv("BALE_BOT_TOKEN", "").strip()
    chat_id = os.getenv("BALE_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return BaleNotifier(token, chat_id)


class BaleNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base = f"https://tapi.bale.ai/bot{token}"

    def send(self, text: str) -> dict:
        r = requests.post(f"{self.base}/sendMessage",
                          json={"chat_id": self.chat_id, "text": text},
                          timeout=15)
        r.raise_for_status()
        return r.json()

    # ---------- قالب پیام‌ها ----------
    def enter(self, symbol: str, cost: float, price: float, sl: float, tp: float):
        self.send(
            "🟢 خرید مجازی\n"
            f"نماد: {symbol}\n"
            f"مبلغ: {cost:,.0f} تومان\n"
            f"قیمت خرید: {price:,.0f}\n"
            f"حد ضرر: {sl:,.0f} | حد سود: {tp:,.0f}"
        )

    def exit(self, symbol: str, entry: float, exit_px: float, cost: float,
             pnl: float, reason: str):
        emo = "🟢" if pnl >= 0 else "🔴"
        reason_fa = {"SL": "حد ضرر", "TP": "حد سود", "SIGNAL": "سیگنال خروج",
                     "TIME": "پایان زمان"}.get(reason, reason)
        self.send(
            f"{emo} فروش مجازی ({reason_fa})\n"
            f"نماد: {symbol}\n"
            f"ورود: {entry:,.0f} → خروج: {exit_px:,.0f}\n"
            f"مبلغ: {cost:,.0f} تومان\n"
            f"سود/ضرر: {pnl:+,.0f} تومان ({pnl / cost * 100:+.2f}٪)"
        )

    def signal_blocked(self, symbols: list, reason: str):
        """سیگنال آمد ولی معامله نشد (جا نبود / بازار بلاک بود)."""
        self.send(
            "⚠️ سیگنال خرید آمد ولی معامله نشد\n"
            f"نمادها: {'، '.join(symbols)}\n"
            f"دلیل: {reason}"
        )

    def daily_report(self, equity: float, starting: float, closed_today: list,
                     n_open: int, total_trades: int, wins: int):
        pnl_total = equity - starting
        pnl_day = sum(t["pnl"] for t in closed_today)
        wr = (wins / total_trades * 100) if total_trades else 0.0
        lines = [
            "📊 گزارش روزانه پورتفوی مجازی",
            f"ارزش کل: {equity:,.0f} تومان ({pnl_total:+,.0f})",
            f"سود/ضرر امروز: {pnl_day:+,.0f} تومان ({len(closed_today)} معامله)",
            f"پوزیشن باز: {n_open} | وین‌ریت کل: {wr:.0f}٪ ({total_trades} معامله)",
        ]
        self.send("\n".join(lines))

    def kill_switch(self, drop_pct: float, cool_h: float):
        self.send(
            "🚨 کلید اضطراری فعال شد\n"
            f"ریزش BTC در ۶۰ دقیقه: {drop_pct:.2f}٪\n"
            "همه پوزیشن‌ها در قیمت بازار بسته شد.\n"
            f"خرید جدید تا {cool_h:.0f} ساعت دیگر متوقف است."
        )

    def daily_halt(self, day_pnl: float, lim_pct: float):
        self.send(
            "🛑 سقف ضرر روزانه فعال شد\n"
            f"ضرر امروز: {day_pnl:,.0f} تومان (سقف {lim_pct:.0f}٪)\n"
            "خرید جدید تا فردا متوقف است (مدیریت پوزیشن‌های باز ادامه دارد)."
        )
