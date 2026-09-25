"""داشبورد وب فارسی بات نوبیتکس — اجرا بدون ترمینال با دابل‌کلیک روی start_dashboard.command"""
import os
import time
import yaml
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from dotenv import load_dotenv, set_key
    load_dotenv()
except Exception:
    set_key = None

from src.nobitex_client import NobitexClient
from src.strategies import apply_all
from src.backtest import backtest, grid_search
from src.screener import screen
from src.whatif import simulate
from src import news as newsmod

st.set_page_config(page_title="بات نوبیتکس", page_icon="📈", layout="wide")
st.markdown("""<style>
  html, body, [class*="st-"] { direction: rtl; text-align: right; font-family: Tahoma, sans-serif; }
  .block-container { max-width: 1200px; }
</style>""", unsafe_allow_html=True)

RTL_COLS = {"symbol": "نماد", "last_close": "قیمت", "score_now": "امتیاز",
            "signal_now": "سیگنال", "enter_now": "ورود؟", "rsi": "RSI",
            "adx": "ADX", "ret_pct": "بازده٪", "winrate": "وین‌ریت٪",
            "pf": "پرافیت‌فکتور", "maxdd": "دراودان٪", "n_trades": "معاملات",
            "rank_score": "رتبه", "rs_vs_btc": "قدرت به BTC٪", "quote": "بازار"}


@st.cache_resource
def get_cfg():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def fresh_cfg():
    """خواندن تازه config (بدون کش) برای لیست کوین‌ها — تا اضافه‌شده‌ها همان لحظه دیده شوند."""
    with open("config.yaml") as f:
        return yaml.safe_load(f)


@st.cache_data(ttl=120)
def fetch(symbol, tf, n):
    cfg = get_cfg()
    c = NobitexClient(cfg["base_url"])
    return c.klines(symbol, tf, n)


@st.cache_data(ttl=600)
def fetch_history(symbol, tf, total):
    cfg = get_cfg()
    c = NobitexClient(cfg["base_url"])
    return c.klines_history(symbol, tf, total)


@st.cache_data(ttl=600)
def get_fng():
    cfg = get_cfg()
    return newsmod.fear_greed(cfg["news"]["fear_greed_url"])


def fa_table(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={k: v for k, v in RTL_COLS.items() if k in df.columns})


# ---------- سایدبار ----------
cfg = get_cfg()
_fresh = fresh_cfg()
st.sidebar.title("⚙️ تنظیمات")
symbols = st.sidebar.multiselect("کوین‌ها", _fresh["symbols"], default=_fresh["symbols"])
tf = st.sidebar.selectbox("تایم‌فریم", ["15", "30", "60", "240", "D"],
                          index=["15", "30", "60", "240", "D"].index(cfg["timeframe"]))
sl = st.sidebar.slider("حد ضرر (×ATR)", 0.5, 3.0, float(cfg["risk"]["sl_atr_mult"]), 0.5)
tp = st.sidebar.slider("حد سود (×ATR)", 1.0, 5.0, float(cfg["risk"]["tp_atr_mult"]), 0.5)
min_score = st.sidebar.slider("حداقل امتیاز ورود", 0.0, 5.0,
                              float(cfg["screener"]["min_signal_score"]), 0.5)
if st.sidebar.button("🔄 به‌روزرسانی داده"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()

st.title("📈 بات معامله‌گر نوبیتکس (کوتاه‌مدت)")

# ---------- چراغ راهنمای خرید ----------
with st.container(border=True):
    st.markdown("### 🚦 الان بخرم یا نه؟")
    try:
        _fg = get_fng()
        # دقیقاً همان داده‌ای که دیمن استفاده می‌کند (BTCIRT + تایم‌فریم پورتفو) تا چراغ با عمل یکی باشد
        try:
            _st = paper_load()
            _ptf = str((_st or {}).get("timeframe", cfg["timeframe"]))
        except Exception:
            _ptf = str(cfg["timeframe"])
        _btc = apply_all(fetch("BTCIRT", _ptf, 500))
        _reg = newsmod.market_regime(_btc, cfg["regime"]["adx_trend_threshold"])
        _gate = newsmod.trade_gate(cfg, _fg, {"score": 0, "n": 0}, _reg)
        if _gate["allow"]:
            st.success("🟢 **بازار مجاز است.** حالا برو به تب 🔍 اسکرینر — هر کوینی که ستون «ورود؟» ✅ دارد، "
                       "سیگنال خریدِ همین الان است (حد ضرر/سود را هم اسلایدر سایدبار تعیین می‌کند).")
        else:
            st.error(f"🔴 **الان نخر.** {' | '.join(_gate['reasons'])} "
                     "صبر کن تا چراغ سبز شود؛ عجله در بازار بد = ضرر.")
        st.caption("قدم‌ها: ۱) همین چراغ سبز باشد ۲) تب اسکرینر → ورود؟ ✅ ۳) تب what-if → مبلغ و سود احتمالی "
                   "۴) تب معامله پیپر → تست مجازی. جزئیات بیشتر در تب 🌡️ وضعیت بازار.")
    except Exception as e:
        st.warning(f"نمی‌توانم وضعیت لحظه‌ای را بگیرم ({e}) — از تب‌ها استفاده کن.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["💭 اگه وارد می‌شدم؟", "🔍 اسکرینر", "🧪 بک‌تست", "🌡️ وضعیت بازار", "🤖 معامله پیپر",
     "🏆 مسابقه استراتژی‌ها"])

# ---------- تب ۱: شبیه‌ساز what-if ----------
with tab1:
    st.subheader("💭 اگه N ساعت پیش با این پول وارد می‌شدم، الان چقدر داشتم؟")
    st.caption("محاسبه با قیمت واقعی کندل‌های نوبیتکس + کارمزد. بازار IRT = تومان، USDT = تتر.")
    c1, c2, c3 = st.columns(3)
    _coins = fresh_cfg().get("paper_coins", ["BTC"])
    base_choice = c1.selectbox("کوین", _coins)
    market_choice = c2.selectbox("بازار", ["تومان (IRT)", "تتر (USDT)"])
    hours_ago = c3.slider("چند ساعت پیش وارد می‌شدی؟", 1, 168, 24)
    c4, c5, c6 = st.columns(3)
    amount_m = c4.number_input("مبلغ (میلیون تومان)", min_value=0.1, value=100.0, step=1.0)
    mode_choice = c5.selectbox("حالت", ["هلد ساده تا الان", "با مدیریت بات (حد ضرر/سود)"])
    cmp_all = c6.checkbox("مقایسه همه کوین‌ها", value=True)
    if st.button("▶️ حساب کن", key="whatif"):
        with st.spinner("دریافت قیمت‌ها..."):
            client = NobitexClient(get_cfg()["base_url"])
            suffix = "IRT" if "تومان" in market_choice else "USDT"
            # نرخ تتر برای تبدیل
            usdt_toman = float(client.klines("USDTIRT", "60", 5)["c"].iloc[-1])
            amount_toman = amount_m * 1_000_000
            # تایم‌فریم مناسب بازه
            ktf, ktotal = ("15", 1000) if hours_ago <= 100 else ("60", 2000)
            mode = "strategy" if "مدیریت" in mode_choice else "hold"
            coins = fresh_cfg().get("paper_coins", [base_choice]) if cmp_all else [base_choice]
            rows, detail = [], None
            prog = st.progress(0)
            for i, coin in enumerate(coins):
                try:
                    sym = f"{coin}{suffix}"
                    raw = client.klines_history(sym, ktf, total=ktotal)
                    df = apply_all(raw)
                    amt_sym = amount_toman if suffix == "IRT" else amount_toman / usdt_toman
                    r = simulate(df, hours_ago, amt_sym, mode, sl, tp,
                                 get_cfg()["risk"]["fee_pct"])
                    val_toman = r["final_value"] if suffix == "IRT" else r["final_value"] * usdt_toman
                    pnl_toman = val_toman - amount_toman
                    rows.append({"کوین": coin,
                                 "قیمت ورود": f"{r['entry_price']:,.0f}",
                                 "قیمت الان": f"{r['now_price']:,.0f}",
                                 "ارزش الان (تومان)": f"{val_toman:,.0f}",
                                 "سود/ضرر (تومان)": f"{pnl_toman:+,.0f}",
                                 "بازده٪": round(pnl_toman / amount_toman * 100, 2),
                                 "وضعیت": r["exit_reason"]})
                    if coin == base_choice:
                        detail = (sym, r)
                except Exception as e:
                    rows.append({"کوین": coin, "وضعیت": f"خطا: {e}"})
                prog.progress((i + 1) / len(coins))
                time.sleep(0.2)
            prog.empty()
        comp = pd.DataFrame(rows).sort_values("بازده٪", ascending=False) if rows and "بازده٪" in pd.DataFrame(rows).columns else pd.DataFrame(rows)
        st.write(f"**نرخ تتر: {usdt_toman:,.0f} تومان**")
        st.dataframe(comp, use_container_width=True)
        if detail and cmp_all:
            best = comp.iloc[0]
            st.success(f"🏆 اگه {hours_ago} ساعت پیش {amount_m:,.0f} میلیون تومان {best['کوین']} می‌خریدی، "
                       f"الان {best['ارزش الان (تومان)']} تومان داشتی ({best['سود/ضرر (تومان)']} تومان).")
        if detail:
            sym, r = detail
            m1, m2, m3 = st.columns(3)
            final_t = r["final_value"] if suffix == "IRT" else r["final_value"] * usdt_toman
            pnl_t = final_t - amount_toman
            m1.metric(f"{base_choice} — ارزش الان", f"{final_t:,.0f} تومان")
            m2.metric("سود / ضرر", f"{pnl_t:+,.0f} تومان", f"{pnl_t / amount_toman * 100:.2f}٪")
            m3.metric("وضعیت", r["exit_reason"])
            fig = go.Figure()
            sl_df = r["slice"]
            fig.add_trace(go.Scatter(x=sl_df["time"], y=sl_df["c"], name="قیمت", line=dict(color="royalblue")))
            fig.add_trace(go.Scatter(x=[r["entry_time"]], y=[r["entry_price"]], mode="markers",
                                     name="ورود فرضی", marker=dict(color="green", size=12, symbol="triangle-up")))
            fig.update_layout(title=f"{sym} از {r['entry_time']} تا الان")
            st.plotly_chart(fig, use_container_width=True)

# ---------- تب ۲: اسکرینر ----------
with tab2:
    st.subheader("رتبه‌بندی کوین‌ها (سیگنال لحظه‌ای + بک‌تست)")
    with st.expander("🔍 کوین‌های جدید نوبیتکس (که زیر نظر نیستند)", expanded=False):
        st.caption("کوین‌هایی که در هر دو بازار تتری و تومانی هستند و حجم روزانه‌شان بالای ۵۰ هزار تتر است. "
                   "تیک بزن و اضافه کن — بدون ری‌استارت از دور بعدی زیر نظر می‌روند.")
        if st.button("🔄 جست‌وجوی کوین‌های جدید", key="disc"):
            with st.spinner("..."):
                try:
                    from src.discover import candidates
                    _cands = candidates(get_cfg(), NobitexClient(get_cfg()["base_url"]))
                    st.session_state["_cands"] = _cands
                except Exception as e:
                    st.error(f"خطا: {e}")
        _cands = st.session_state.get("_cands", [])
        if _cands:
            st.dataframe(pd.DataFrame(_cands), use_container_width=True)
            _pick = st.multiselect("انتخاب برای اضافه شدن", [c["coin"] for c in _cands])
            if st.button("➕ اضافه کن", key="disc_add") and _pick:
                with st.spinner("بررسی کندل‌ها..."):
                    try:
                        from src.discover import verify
                        cc = NobitexClient(get_cfg()["base_url"])
                        added, failed = [], []
                        cfg_all = get_cfg()
                        for base in _pick:
                            try:
                                u, i = verify(cc, base)
                                if u not in cfg_all["symbols"]:
                                    cfg_all["symbols"].append(u)
                                if base not in cfg_all.get("paper_coins", []):
                                    cfg_all.setdefault("paper_coins", []).append(base)
                                added.append(base)
                            except Exception as e:
                                failed.append(f"{base} ({str(e)[:50]})")
                            time.sleep(0.2)
                        with open("config.yaml", "w") as f:
                            yaml.safe_dump(cfg_all, f, allow_unicode=True)
                        st.cache_data.clear()
                        st.cache_resource.clear()
                        if added:
                            st.success(f"اضافه شد: {'، '.join(added)} — صفحه رفرش می‌شود...")
                            time.sleep(1)
                            st.rerun()
                        if failed:
                            st.error(f"ناموفق (کندل ندارد): {'، '.join(failed)}")
                    except Exception as e:
                        st.error(f"خطا: {e}")
    if not symbols:
        st.warning("کوینی انتخاب نشده.")
    else:
        with st.spinner("دریافت داده از نوبیتکس..."):
            data, errs = {}, []
            prog = st.progress(0)
            for i, s in enumerate(symbols):
                try:
                    data[s] = fetch(s, tf, 500)
                except Exception as e:
                    errs.append(f"{s}: {e}")
                prog.progress((i + 1) / len(symbols))
                time.sleep(0.2)
            prog.empty()
        for e in errs:
            st.error(e)
        if data:
            live_cfg = {**cfg, "screener": {**cfg["screener"], "min_signal_score": min_score}}
            table = screen(data, live_cfg)
            if table.empty:
                st.warning("هیچ کوینی از فیلتر حجم عبور نکرد.")
            else:
                only_enter = st.checkbox("فقط کوین‌هایی که **الان سیگنال خرید** دارند ✅", value=False)
                show = table[table["enter_now"]] if only_enter else table
                if show.empty:
                    st.info("در حال حاضر هیچ سیگنال خریدی نیست — یعنی **الان وقت خرید نیست**، صبر کن. "
                            "تیک بالا را بردار تا همه را ببینی.")
                else:
                    st.dataframe(fa_table(show), use_container_width=True)
                fig = px.bar(table, x="symbol", y="rank_score", color="enter_now",
                             title="امتیاز رتبه‌بندی", color_discrete_map={True: "green", False: "gray"})
                st.plotly_chart(fig, use_container_width=True)
                best = table.iloc[0]
                st.success(f"🏆 بهترین گزینه: **{best['symbol']}** | قیمت {best['last_close']} | "
                           f"ورود؟ {'✅ بله' if best['enter_now'] else '❌ خیر'} | "
                           f"RSI {best['rsi']} | بازده بک‌تست {best['ret_pct']}٪")

# ---------- تب ۳: بک‌تست ----------
with tab3:
    st.subheader("بک‌تست تکی + بهینه‌سازی حد ضرر/سود")
    sym = st.selectbox("نماد", cfg["symbols"])
    deep_tf = st.selectbox("تایم‌فریم بک‌تست عمیق", ["60", "240", "D", "15"], index=0,
                           help="نوبیتکس برای 15m فقط ~۷ روز تاریخچه دارد؛ 60m چند ماه.")
    if st.button("▶️ اجرای بک‌تست", key="bt"):
        with st.spinner("..."):
            raw = fetch_history(sym, deep_tf, 2000 if deep_tf in ("60", "240", "D") else 1000)
            df = apply_all(raw, min_score=min_score)
            st.info(f"{len(raw)} کندل از {raw['time'].min()} تا {raw['time'].max()} | "
                    f"سیگنال ورود: {int(df['enter_long'].sum())}")
            g = grid_search(df)
            st.write("**بهترین ترکیب‌های SL/TP:**")
            st.dataframe(g.head(5), use_container_width=True)
            r = backtest(df, sl_atr=sl, tp_atr=tp, fee_pct=cfg["risk"]["fee_pct"],
                         max_holding=cfg["risk"]["max_holding_candles"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("بازده", f"{r['total_return_pct']}٪")
            c2.metric("وین‌ریت", f"{r['winrate_pct']}٪")
            c3.metric("پرافیت‌فکتور", r['profit_factor'])
            c4.metric("معاملات", r['n_trades'])
            # نمودار قیمت + نقاط ورود/خروج
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["time"], y=df["c"], name="قیمت", line=dict(color="royalblue")))
            tr = r["trades"]
            if not tr.empty:
                entries = df.loc[tr["entry_idx"].clip(0, len(df) - 1)]
                fig.add_trace(go.Scatter(x=entries["time"], y=tr["entry"].values,
                                         mode="markers", name="ورود",
                                         marker=dict(color="green", size=9, symbol="triangle-up")))
                reason_color = {"SL": "red", "TP": "green", "SIGNAL": "orange", "TIME": "gray", "END": "gray"}
                for reason, grp in tr.groupby("reason"):
                    ex = df.loc[grp["exit_idx"].clip(0, len(df) - 1)]
                    fig.add_trace(go.Scatter(x=ex["time"], y=grp["exit"].values, mode="markers",
                                             name=f"خروج {reason}",
                                             marker=dict(color=reason_color.get(reason, "gray"),
                                                         size=9, symbol="triangle-down")))
            fig.update_layout(title=f"{sym} — ورود/خروج‌ها", xaxis_title="", yaxis_title="قیمت")
            st.plotly_chart(fig, use_container_width=True)
            if not tr.empty:
                st.write("**معاملات:**")
                st.dataframe(tr.tail(30), use_container_width=True)

# ---------- تب ۴: وضعیت بازار ----------
with tab4:
    st.subheader("سنتیمنت و رژیم بازار")
    fg = get_fng()
    c1, c2 = st.columns(2)
    c1.metric("شاخص ترس و طمع", f"{fg['value']} ({fg.get('label', '')})", f"میانگین هفته: {fg['trend']:.0f}")
    try:
        _st4 = paper_load()
        _ptf4 = str((_st4 or {}).get("timeframe", cfg["timeframe"]))
        btc = apply_all(fetch("BTCIRT", _ptf4, 500))
        reg = newsmod.market_regime(btc, cfg["regime"]["adx_trend_threshold"])
        c2.metric("رژیم BTC", reg["regime"], f"ADX {reg.get('adx')}")
        gate = newsmod.trade_gate(cfg, fg, {"score": 0, "n": 0}, reg)
        if gate["allow"]:
            st.success("✅ ورود مجاز است — " + " | ".join(gate["reasons"]))
        else:
            st.error("⛔ ورود بلاک است — " + " | ".join(gate["reasons"]))
    except Exception as e:
        st.error(f"خطا در دریافت داده BTC: {e}")

# ---------- تب ۵: پورتفوی مجازی ----------
with tab5:
    from src.paper import load as paper_load, new_account, save as paper_save, equity as paper_equity
    st.subheader("💼 پورتفوی مجازی — پول فرضی بده، خودش می‌خرد و می‌فروشد")
    st.caption("بازار تومانی (IRT) + حد ضرر/سود واقعی + کارمزد. وضعیت ذخیره می‌شود؛ صفحه را ببند و ساعات بعد برگرد.")
    with st.expander("📩 اطلاع‌رسانی به گروه بله", expanded=False):
        st.caption("هر خرید/فروش (با مبلغ و سود/ضرر) به گروهت پیام می‌دهد.")
        _tok = st.text_input("توکن ربات بله", value=os.getenv("BALE_BOT_TOKEN", ""),
                             type="password", help="از BotFather بله بگیر")
        _cid = st.text_input("آیدی گروه", value=os.getenv("BALE_CHAT_ID", "5204613701"))
        cc1, cc2 = st.columns(2)
        if cc1.button("💾 ذخیره", key="bale_save"):
            if set_key is None:
                st.error("پکیج python-dotenv نصب نیست.")
            else:
                for k, v in {"BALE_BOT_TOKEN": _tok.strip(), "BALE_CHAT_ID": _cid.strip()}.items():
                    set_key(".env", k, v)
                    os.environ[k] = v
                st.success("ذخیره شد.")
        if cc2.button("📨 ارسال پیام تست", key="bale_test"):
            os.environ["BALE_BOT_TOKEN"] = _tok.strip()
            os.environ["BALE_CHAT_ID"] = _cid.strip()
            from src.notify import get_notifier
            n = get_notifier()
            if not n:
                st.error("توکن و آیدی گروه را وارد کن.")
            else:
                try:
                    n.send("✅ بات نوبیتکس به گروه وصل شد. از این به بعد خرید/فروش‌ها اینجا اطلاع‌رسانی می‌شود.")
                    st.success("پیام تست ارسال شد — گروه را چک کن.")
                except Exception as e:
                    st.error(f"ارسال ناموفق: {e}")
    acct = paper_load()
    c1, c2, c3 = st.columns(3)
    cap_m = c1.number_input("سرمایه (میلیون تومان)", min_value=1.0, value=100.0, step=10.0)
    interval_min = c2.selectbox("هر چند دقیقه چک کند؟", [5, 15, 30, 60], index=1)
    auto = c3.toggle("معامله خودکار روشن", value=True if acct is None else bool(acct.get("active", True)))
    def_ms = float((acct or {}).get("min_score", cfg["screener"]["min_signal_score"]))
    ms = st.slider("حداقل امتیاز ورود برای معامله‌گر آزمایشی", 0.0, 6.0, def_ms, 0.5,
                   help="جمع امتیاز استراتژی‌های موافق (حداکثر ~۷.۵). بالاتر = سخت‌گیرانه‌تر و معاملات کمتر. "
                        "مستقیم روی ورودهای پورتفو اثر می‌گذارد.")
    def_mp = int((acct or {}).get("max_open_positions", cfg["risk"]["max_open_positions"]))
    mp = st.slider("حداکثر کوین هم‌زمان در پورتفو", 1, 10, def_mp, 1,
                   help="بیشتر = تنوع بیشتر ولی هر خرید کوچک‌تر (سرمایه ÷ تعداد).")
    _tfs = ["5", "15", "30", "60"]
    def_tf = str((acct or {}).get("timeframe", cfg["timeframe"]))
    tf_m = st.selectbox("تایم‌فریم معامله‌گر (دقیقه)", _tfs, index=_tfs.index(def_tf) if def_tf in _tfs else 1,
                        help="۵ = اسکالپ تند (سیگنال بیشتر، خطای بیشتر) | ۶۰ = آرام‌تر و مطمئن‌تر. روی خریدهای بعدی اثر می‌گذارد.")
    _all_coins = fresh_cfg().get("paper_coins", ["BTC"])
    def_coins = (acct or {}).get("coins", _all_coins)
    picked = st.multiselect("کوین‌های زیر نظر", _all_coins, default=[c for c in def_coins if c in _all_coins])
    def_sl = float((acct or {}).get("sl_atr", cfg["risk"]["sl_atr_mult"]))
    def_tp = float((acct or {}).get("tp_atr", cfg["risk"]["tp_atr_mult"]))
    sc1, sc2 = st.columns(2)
    sl_m = sc1.slider("حد ضرر (×ATR)", 0.5, 3.0, def_sl, 0.5)
    tp_m = sc2.slider("حد سود (×ATR)", 1.0, 5.0, def_tp, 0.5)
    st.markdown("**🛡️ مدیریت ریسک**")
    def_trail = float((acct or {}).get("trail_atr", cfg["risk"].get("trailing_atr_mult", 0.0) or 0.0))
    def_kill = float((acct or {}).get("kill_drop_pct", cfg["risk"].get("kill_drop_pct", 3.0)))
    def_cool = float((acct or {}).get("kill_cool_h", cfg["risk"].get("kill_cool_h", 4)))
    def_day = float((acct or {}).get("max_daily_loss_pct", cfg["risk"].get("max_daily_loss_pct", 3.0)))
    rc1, rc2 = st.columns(2)
    trail_m = rc1.slider("تریلینگ‌استاپ (×ATR) — ۰ = خاموش", 0.0, 5.0, def_trail, 0.5,
                         help="وقتی قیمت بالا می‌رود حد ضرر هم بالا می‌آید و سود قفل می‌شود. ۲.۵ به بالا پیشنهاد می‌شود.")
    day_m = rc2.slider("سقف ضرر روزانه (٪) — ۰ = خاموش", 0.0, 10.0, def_day, 0.5,
                       help="اگه ضرر امروز به این سقف برسد، خرید تا فردا متوقف می‌شود.")
    rc3, rc4 = st.columns(2)
    kill_m = rc3.slider("کیل‌سوییچ: ریزش BTC در ۶۰ دقیقه (٪) — ۰ = خاموش", 0.0, 10.0, def_kill, 0.5,
                        help="اگه بیت‌کوین این‌قدر بریزد، همه فوری بسته و خرید متوقف می‌شود.")
    cool_m = rc4.slider("توقف خرید بعد از کیل‌سوییچ (ساعت)", 1.0, 12.0, def_cool, 1.0)
    b1, b2, b3 = st.columns(3)
    if b1.button("🟢 شروع / شروع مجدد با این مبلغ", key="paper_start"):
        acct = new_account(cap_m * 1_000_000)
        acct["active"] = True  # دکمه شروع یعنی فعال — مستقل از وضعیت تاگل
        acct["interval_min"] = interval_min
        acct["min_score"] = ms
        acct["max_open_positions"] = mp
        acct["coins"] = picked or _all_coins
        acct["timeframe"] = tf_m
        acct["sl_atr"] = sl_m
        acct["tp_atr"] = tp_m
        acct["trail_atr"] = trail_m
        acct["kill_drop_pct"] = kill_m
        acct["kill_cool_h"] = cool_m
        acct["max_daily_loss_pct"] = day_m
        acct["next_scan"] = 0
        paper_save(acct)
        st.rerun()
    if b2.button("⏸️ توقف / ▶️ ادامه", key="paper_pause"):
        if acct is not None:
            acct["active"] = not acct.get("active", True)
            paper_save(acct)
            st.rerun()
    if b3.button("🗑️ پاک کردن پورتفو", key="paper_reset"):
        import os as _os
        from src.paper import STATE_FILE as _SF
        if _os.path.exists(_SF):
            _os.remove(_SF)
        acct = None
        st.rerun()
    # --- وضعیت دیمن پس‌زمینه ---
    import json as _json
    _hb_path = "daemon_heartbeat.json"
    _daemon_ok, _hb_age = False, None
    if os.path.exists(_hb_path):
        try:
            _hb_age = time.time() - _json.load(open(_hb_path))["time"]
            _daemon_ok = _hb_age < 120
        except Exception:
            pass
    if _daemon_ok:
        st.success(f"✅ موتور معامله در پس‌زمینه فعال است (آخرین ضربان {int(_hb_age)} ثانیه پیش) — "
                   "بستن مرورگر یا ترمینال مشکلی ندارد.")
    else:
        st.error("⛔ موتور پس‌زمینه خاموش است! فایل start_dashboard.command را دوباره اجرا کن "
                 "(بدون آن معامله‌ای انجام نمی‌شود).")
    if acct is None:
        st.info("هنوز پورتفویی نساخته‌ای — مبلغ را بزن و «شروع» را بزن.")
    else:
        acct["active"] = auto
        acct["interval_min"] = interval_min
        acct["min_score"] = ms
        acct["max_open_positions"] = mp
        acct["coins"] = picked or _all_coins
        acct["timeframe"] = tf_m
        acct["sl_atr"] = sl_m
        acct["tp_atr"] = tp_m
        acct["trail_atr"] = trail_m
        acct["kill_drop_pct"] = kill_m
        acct["kill_cool_h"] = cool_m
        acct["max_daily_loss_pct"] = day_m
        paper_save(acct)
        # --- نمایش وضعیت (فقط خواندنی، بدون معامله) ---
        a = paper_load()
        _now = time.time()
        _tr = float(a.get("trail_atr", 0) or 0)
        _kd = float(a.get("kill_drop_pct", 0) or 0)
        _dl = float(a.get("max_daily_loss_pct", 0) or 0)
        st.caption(f"🛡️ ریسک فعال: تریلینگ {'✅ روشن (' + str(_tr) + '×)' if _tr > 0 else '❌ خاموش'} | "
                   f"کیل‌سوییچ {'✅ ' + str(_kd) + '٪' if _kd > 0 else '❌ خاموش'} | "
                   f"سقف ضرر روزانه {'✅ ' + str(_dl) + '٪' if _dl > 0 else '❌ خاموش'} | "
                   f"حد ضرر {a.get('sl_atr')}× / حد سود {a.get('tp_atr')}×")
        _now = time.time()
        if a.get("kill_until", 0) > _now:
            st.warning("🚨 دوره خنک‌سازی کیل‌سوییچ فعال است — خرید جدید متوقف تا پایان دوره.")
        if a.get("halted_until", 0) > _now:
            st.warning("🛑 سقف ضرر روزانه فعال است — خرید جدید تا فردا متوقف است.")
        client = NobitexClient(get_cfg()["base_url"])

        @st.cache_data(ttl=60)
        def _live(symbols):
            out = {}
            cc = NobitexClient(get_cfg()["base_url"])
            for s in symbols:
                try:
                    out[s] = float(cc.klines(s, "15", 5)["c"].iloc[-1])
                except Exception:
                    pass
            return out

        live_prices = _live(tuple(a["positions"].keys()))
        for s, p in a["positions"].items():
            live_prices.setdefault(s, p["entry"])
        eq = paper_equity(a, live_prices)
        pnl = eq - a["starting_cash"]

        def _m(x):
            return f"{x / 1_000_000:,.1f} م"  # میلیون تومان، فشرده برای جا شدن

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("ارزش کل", _m(eq), _m(pnl))
        m2.metric("بازده", f"{pnl / a['starting_cash'] * 100:+.2f}٪")
        m3.metric("نقد", _m(a["cash"]))
        m4.metric("پوزیشن باز", len(a["positions"]))
        st.caption(f"آخرین اسکن دیمن: {a.get('last_scan')} | وضعیت: فعال ✅" if a.get("active")
                   else f"آخرین اسکن دیمن: {a.get('last_scan')} | وضعیت: متوقف ⏸️ (تاگل «معامله خودکار روشن» خاموش است — روشنش کن)")
        if a["positions"]:
            st.write("**پوزیشن‌های باز:**")
            rows = [{"نماد": s, "ورود": f"{p['entry']:,.0f}",
                     "قیمت الان": f"{live_prices.get(s, p['entry']):,.0f}",
                     "حد ضرر": f"{p['sl']:,.0f}", "حد سود": f"{p['tp']:,.0f}",
                     "سود/ضرر": f"{(live_prices.get(s, p['entry']) - p['entry']) * p['amount']:+,.0f}"}
                    for s, p in a["positions"].items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        if a["history"]:
            st.write("**معاملات بسته‌شده:**")
            st.dataframe(pd.DataFrame(a["history"]).tail(20), use_container_width=True)
        if len(a.get("snapshots", [])) > 1:
            snap = pd.DataFrame(a["snapshots"])
            snap["time"] = pd.to_datetime(snap["time"])
            fig = px.line(snap, x="time", y="equity", title="نمودار ارزش پورتفو")
            fig.add_hline(y=a["starting_cash"], line_dash="dash", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)
        if st.button("🔄 همین الان یک دور اسکن کن", key="paper_once"):
            open("paper_scan.flag", "w").close()
            st.info("درخواست ثبت شد — دیمن تا ~۳۰ ثانیه دیگر اسکن می‌کند. صفحه را رفرش کن.")

# ---------- تب ۶: مسابقه استراتژی‌ها ----------
with tab6:
    from src.league import STRATS, RULES_FA, CAPITAL_EACH, league_equity, league_stats, new_league, ensure_league
    st.subheader("🏆 مسابقه استراتژی‌ها — کدوم بهتره؟")
    st.info(RULES_FA)
    acct6 = paper_load()
    if acct6 is None:
        st.warning("اول در تب 💼 پورتفو «شروع» را بزن تا مسابقه هم شروع شود.")
    else:
        lg = ensure_league(acct6.get("league"))
        if lg is None:
            st.info("لیگ از اسکن بعدی دیمن شروع می‌شود. دکمه «همین الان اسکن کن» را در تب پورتفو بزن.")
        else:
            prices6 = acct6.get("last_prices", {})
            rows = []
            for name, meta in STRATS.items():
                s = league_stats(lg[name], prices6)
                rows.append({"استراتژی": meta["fa"], "ارزش": f"{s['equity']:,.0f}",
                             "بازده٪": s["ret_pct"], "معاملات": s["n"],
                             "وین‌ریت٪": s["winrate"], "باز": s["n_open"]})
            board = pd.DataFrame(rows).sort_values("بازده٪", ascending=False).reset_index(drop=True)
            st.dataframe(board, use_container_width=True)
            if not board.empty:
                champ = board.iloc[0]
                st.success(f"🏆 الان بهترین: **{champ['استراتژی']}** با بازده {champ['بازده٪']}٪ "
                           f"({champ['معاملات']} معامله، وین‌ریت {champ['وین‌ریت٪']}٪)")
                fig = px.bar(board, x="استراتژی", y="بازده٪", title="بازده هر استراتژی",
                             color="بازده٪", color_continuous_scale=["red", "gray", "green"])
                st.plotly_chart(fig, use_container_width=True)
            for name, meta in STRATS.items():
                with st.expander(f"{meta['fa']} — جزئیات معاملات"):
                    h = lg[name]["history"]
                    if h:
                        st.dataframe(pd.DataFrame(h).tail(20), use_container_width=True)
                    else:
                        st.caption("هنوز معامله‌ای نداشته.")
                    op = lg[name]["positions"]
                    if op:
                        st.write("پوزیشن‌های باز:", list(op.keys()))
            if st.button("🗑️ ریست مسابقه (هر ۴ نفر از ۱۰۰ میلیون شروع کنند)", key="league_reset"):
                acct6["league"] = new_league()
                paper_save(acct6)
                st.rerun()
