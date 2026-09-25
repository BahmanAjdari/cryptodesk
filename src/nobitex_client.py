"""کلاینت رسمی Nobitex API v2 — مستندات: https://apidocs.nobitex.ir/"""
import time
import requests
import pandas as pd


class NobitexClient:
    def __init__(self, base_url="https://apiv2.nobitex.ir", token=None, api_key=None,
                 bot_name="TraderBot/nobitex-bot-1.0.0"):
        self.base = base_url.rstrip("/")
        self.token = token
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": bot_name,
            "Content-Type": "application/json",
        })

    # ---------- internal ----------
    def _auth_headers(self):
        h = {}
        if self.token:
            h["Authorization"] = f"Token {self.token}"
        elif self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _get(self, path, params=None, auth=False):
        r = self.session.get(self.base + path, params=params,
                             headers=self._auth_headers() if auth else None,
                             timeout=20)
        r.raise_for_status()
        return r.json()

    def _post(self, path, body=None, auth=True):
        r = self.session.post(self.base + path, json=body or {},
                              headers=self._auth_headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    # ---------- Market data (public) ----------
    def stats(self, srcCurrency=None, dstCurrency=None):
        """GET /market/stats — آمار بازار (آخرین قیمت، حجم، ...)"""
        p = {}
        if srcCurrency:
            p["srcCurrency"] = srcCurrency
        if dstCurrency:
            p["dstCurrency"] = dstCurrency
        return self._get("/market/stats", params=p)

    def orderbook(self, symbol):
        """GET /v3/orderbook/{symbol} — دفتر سفارشات. symbol مثل BTCUSDT یا all"""
        return self._get(f"/v3/orderbook/{symbol}")

    def trades(self, symbol):
        """GET /v2/trades/{symbol} — ۲۰ معامله اخیر"""
        return self._get(f"/v2/trades/{symbol}")

    def ohlc(self, symbol, resolution="15", to_ts=None, countback=500, page=1):
        """GET /market/udf/history — کندل‌ها. symbol مثل BTCUSDT"""
        if to_ts is None:
            to_ts = int(time.time())
        params = {"symbol": symbol, "resolution": str(resolution),
                  "to": int(to_ts), "countback": int(countback), "page": int(page)}
        return self._get("/market/udf/history", params=params)

    def klines(self, symbol, resolution="15", countback=500) -> pd.DataFrame:
        """کندل‌ها به DataFrame با ستون‌های time,o,h,l,c,v"""
        raw_pages, page, to_ts = [], 1, int(time.time())
        # نوبیتکس در هر درخواست max 500 کندل می‌دهد؛ برای بیشتر، صفحه‌بندی می‌کنیم
        while len(raw_pages) < 1:  # فعلاً یک صفحه کافی است (countback<=500)
            j = self.ohlc(symbol, resolution, to_ts, countback, page)
            if j.get("s") != "ok":
                raise RuntimeError(f"OHLC error for {symbol}: {j}")
            df = pd.DataFrame({"time": j["t"], "o": j["o"], "h": j["h"],
                               "l": j["l"], "c": j["c"], "v": j["v"]})
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            raw_pages.append(df)
            break
        df = pd.concat(raw_pages).sort_values("time").reset_index(drop=True)
        for col in "ohlcv":
            df[col] = df[col].astype(float)
        return df

    def klines_history(self, symbol, resolution="15", total=1500) -> pd.DataFrame:
        """دریافت بیش از ۵۰۰ کندل با صفحه‌بندی (برای بک‌تست)"""
        out, page, to_ts = [], 1, int(time.time())
        while sum(len(d) for d in out) < total:
            j = self.ohlc(symbol, resolution, to_ts, 500, page)
            if j.get("s") != "ok":
                break
            df = pd.DataFrame({"t": j["t"], "o": j["o"], "h": j["h"],
                               "l": j["l"], "c": j["c"], "v": j["v"]})
            if df.empty:
                break
            out.append(df)
            to_ts = int(df["t"].min()) - 1
            page = 1
            if len(df) < 500:
                break
            time.sleep(0.3)  # احترام به ریت‌لیمیت ۶۰/min
        if not out:
            raise RuntimeError(f"No OHLC data for {symbol}")
        df = pd.concat(out).drop_duplicates("t").sort_values("t").reset_index(drop=True)
        df["time"] = pd.to_datetime(df["t"], unit="s", utc=True)
        df = df.rename(columns={"o": "o", "h": "h", "l": "l", "c": "c", "v": "v"})
        for col in "ohlcv":
            df[col] = df[col].astype(float)
        return df[["time", "o", "h", "l", "c", "v"]].tail(total).reset_index(drop=True)

    # ---------- Spot trading (private, نیازمند Token یا API-Key با دسترسی TRADE) ----------
    def order_add(self, *, side, src, dst, amount, price=None, execution="market",
                  stop_price=None, stop_limit_price=None, mode=None, client_order_id=None):
        """POST /market/orders/add — ثبت سفارش اسپات (limit/market/stop/OCO)"""
        body = {"type": side, "execution": execution,
                "srcCurrency": src.lower(), "dstCurrency": dst.lower(),
                "amount": str(amount)}
        if price is not None:
            body["price"] = str(price)
        if stop_price is not None:
            body["stopPrice"] = str(stop_price)
        if stop_limit_price is not None:
            body["stopLimitPrice"] = str(stop_limit_price)
        if mode:
            body["mode"] = mode
        if client_order_id:
            body["clientOrderId"] = client_order_id
        return self._post("/market/orders/add", body)

    def buy_market(self, src, dst, amount, price_hint=None):
        return self.order_add(side="buy", src=src, dst=dst, amount=amount,
                              price=price_hint, execution="market")

    def sell_market(self, src, dst, amount, price_hint=None):
        return self.order_add(side="sell", src=src, dst=dst, amount=amount,
                              price=price_hint, execution="market")

    def oco_exit(self, src, dst, amount, take_profit_price, stop_price, stop_limit_price,
                 client_order_id=None):
        """سفارش OCO برای خروج: هم‌زمان حد سود + حد ضرر (با پر شدن یکی، دیگری لغو می‌شود)"""
        # برای پوزیشن لانگِ اسپات، خروج = فروش OCO
        return self.order_add(side="sell", src=src, dst=dst, amount=amount,
                              price=take_profit_price, stop_price=stop_price,
                              stop_limit_price=stop_limit_price, mode="oco",
                              client_order_id=client_order_id)

    def order_status(self, order_id=None, client_order_id=None):
        body = {}
        if order_id:
            body["id"] = order_id
        if client_order_id:
            body["clientOrderId"] = client_order_id
        return self._post("/market/orders/status", body)

    def order_cancel(self, order_id=None, client_order_id=None):
        body = {}
        if order_id:
            body["order"] = order_id
        if client_order_id:
            body["clientOrderId"] = client_order_id
        return self._post("/market/orders/cancel", body)

    def orders_list(self, status="open", **filters):
        params = {"status": status, **filters}
        return self._get("/market/orders/list", params=params, auth=True)

    def wallets(self):
        """موجودی کیف‌پول‌ها"""
        try:
            return self._get("/users/wallets/list", auth=True)
        except Exception:
            return self._post("/users/wallets/balance", {})
