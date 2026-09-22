import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
import requests
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from scipy.stats import norm as scipy_norm
from scipy.optimize import brentq

# ==========================================
# 0. 頁面設定
# ==========================================
st.set_page_config(
    page_title="MSTR 股價監控戰情室（雲端版）",
    layout="wide",
    initial_sidebar_state="expanded"
)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# ==========================================
# Session State 初始化
# ==========================================
DEFAULTS = {
    "MSTR_BTC_HOLDINGS":   846000,
    "MSTR_AVG_COST":       75416,
    "MSTR_BASIC_SHARES":   420507000,
    "MSTR_TOTAL_DEBT_M":   6714,
    "MSTR_TOTAL_PREF_M":   14294,
    "MSTR_CASH_RESERVE_M": 6092,
    "MSTR_FDSO":           429839000,
}
for k, v in DEFAULTS.items():
    if f"{k}_val" not in st.session_state:
        st.session_state[f"{k}_val"] = v

def save_params():
    for k in DEFAULTS.keys():
        if k in st.session_state:
            st.session_state[f"{k}_val"] = st.session_state[k]

# ── 備兌買權部位 Session State ──────────────────────────
CC_POSITIONS_DEFAULT = [
    {"id": 3, "label": "MSTR Dec18'26 $190", "strike": 190.0, "expiry": "2026-12-18", "contracts": 1,  "net_cash": 400.0,  "market_price": 5.35, "ticker": "MSTR", "active": True},
    {"id": 4, "label": "MSTR Dec18'26 $195", "strike": 195.0, "expiry": "2026-12-18", "contracts": 1,  "net_cash": 400.0,  "market_price": 4.85, "ticker": "MSTR", "active": True},
    {"id": 5, "label": "MSTR Jan15'27 $190", "strike": 190.0, "expiry": "2027-01-15", "contracts": 1,  "net_cash": 500.0,  "market_price": 7.43, "ticker": "MSTR", "active": True},
    {"id": 6, "label": "MSTR Jan15'27 $195", "strike": 195.0, "expiry": "2027-01-15", "contracts": 20, "net_cash": 4000.0, "market_price": 6.80, "ticker": "MSTR", "active": True},
    {"id": 8, "label": "MSTR Jan15'27 $230", "strike": 230.0, "expiry": "2027-01-15", "contracts": 6,  "net_cash": 7270.0, "market_price": 12.12, "ticker": "MSTR", "active": True},
    {"id": 9, "label": "MSTR Jan15'27 $235", "strike": 235.0, "expiry": "2027-01-15", "contracts": 2,  "net_cash": 2373.0, "market_price": 11.87, "ticker": "MSTR", "active": True},
    {"id": 7, "label": "COIN Nov20'26 $210", "strike": 210.0, "expiry": "2026-11-20", "contracts": 3,  "net_cash": 1084.0, "market_price": 8.79, "ticker": "COIN", "active": True},
]
if "cc_positions" not in st.session_state:
    st.session_state["cc_positions"] = CC_POSITIONS_DEFAULT

# ==========================================
# 共用函數：Black-Scholes Greeks
# ==========================================
def bs_call_full(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0), 0, 0, 0, 0, 0
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    price    = S*scipy_norm.cdf(d1) - K*math.exp(-r*T)*scipy_norm.cdf(d2)
    delta    = scipy_norm.cdf(d1)
    gamma    = scipy_norm.pdf(d1) / (S * sigma * math.sqrt(T))
    theta    = (-(S*scipy_norm.pdf(d1)*sigma)/(2*math.sqrt(T)) - r*K*math.exp(-r*T)*scipy_norm.cdf(d2)) / 365
    vega     = S * scipy_norm.pdf(d1) * math.sqrt(T) / 100
    prob_itm = scipy_norm.cdf(d2)
    return price, delta, gamma, theta, vega, prob_itm

def bs_call(S, K, T, r, sigma):
    p, d, g, t, v, prob = bs_call_full(S, K, T, r, sigma)
    return p, d, t, prob

def implied_vol_from_price(S, K, T, r, market_price):
    if T <= 0 or S <= 0 or K <= 0 or market_price <= 0:
        return 0
    def objective(sigma):
        p, _, _, _ = bs_call(S, K, T, r, sigma)
        return p - market_price
    try:
        return brentq(objective, 0.01, 5.0)
    except:
        return 0

# ==========================================
# 1. 數據抓取模組
# ==========================================
@st.cache_data(ttl=30)
def fetch_btc_price():
    try:
        btc = yf.Ticker("BTC-USD")
        df = btc.history(period="2d", interval="5m")
        if not df.empty:
            price = float(df['Close'].iloc[-1])
            prev  = float(df['Close'].iloc[0])
            delta = (price - prev) / prev * 100
            return price, delta
        return 0, 0
    except:
        return 0, 0

@st.cache_data(ttl=60)
def fetch_mstr_data():
    """MSTR 股價與歷史數據（五層備援）"""
    hist = None

    # ── 第一層：yfinance 6 個月日線 ──────────────
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="6mo", interval="1d")
        if hist.empty or np.isnan(hist['Close'].iloc[-1]):
            hist = None
    except:
        hist = None

    # ── 第二層：yfinance 3 個月日線 ──────────────
    if hist is None:
        try:
            mstr = yf.Ticker("MSTR")
            hist = mstr.history(period="3mo", interval="1d")
            if hist.empty or np.isnan(hist['Close'].iloc[-1]):
                hist = None
        except:
            hist = None

    # ── 第三層：yfinance 1 個月日線 ──────────────
    if hist is None:
        try:
            mstr = yf.Ticker("MSTR")
            hist = mstr.history(period="1mo", interval="1d")
            if hist.empty or np.isnan(hist['Close'].iloc[-1]):
                hist = None
        except:
            hist = None

    # ── 第四層：Stooq CSV 備援 ──────────────────
    if hist is None:
        try:
            stooq_url = "https://stooq.com/q/d/l/?s=mstr.us&i=d"
            df_stooq = pd.read_csv(stooq_url)
            if not df_stooq.empty:
                df_stooq['Date'] = pd.to_datetime(df_stooq['Date'])
                df_stooq = df_stooq.set_index('Date').sort_index()
                df_stooq = df_stooq.tail(130)
                if len(df_stooq) >= 20:
                    df_stooq.columns = [c.capitalize() for c in df_stooq.columns]
                    hist = df_stooq
        except:
            pass

    # ── 第五層：Yahoo Finance 直接 HTTP 請求 ──────
    if hist is None:
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/MSTR?range=6mo&interval=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            quotes = result["indicators"]["quote"][0]
            df_yahoo = pd.DataFrame({
                "Date": pd.to_datetime(timestamps, unit="s"),
                "Open": quotes["open"],
                "High": quotes["high"],
                "Low": quotes["low"],
                "Close": quotes["close"],
                "Volume": quotes["volume"],
            }).dropna()
            df_yahoo = df_yahoo.set_index("Date").sort_index()
            if len(df_yahoo) >= 20:
                hist = df_yahoo
        except:
            pass

    # ── 全部失敗：回傳 None ─────────────────────
    if hist is None or hist.empty:
        return None

    # ── 計算技術指標 ─────────────────────────────
    price = float(hist['Close'].iloc[-1])
    delta = hist['Close'].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

    ma20 = float(hist['Close'].rolling(20).mean().iloc[-1])
    ma60 = float(hist['Close'].rolling(60).mean().iloc[-1]) if len(hist) >= 60 else ma20

    ma20_series = hist['Close'].rolling(20).mean()
    std20       = hist['Close'].rolling(20).std()
    bb_upper    = float((ma20_series + 2 * std20).iloc[-1])
    bb_lower    = float((ma20_series - 2 * std20).iloc[-1])

    log_ret = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
    hv30    = float(log_ret.tail(30).std() * np.sqrt(252)) if len(log_ret) >= 30 else 0

    return {
        'price': price, 'rsi': rsi,
        'ma20': ma20, 'ma60': ma60,
        'bb_upper': bb_upper, 'bb_lower': bb_lower,
        'hv30': hv30, 'hist': hist,
    }

@st.cache_data(ttl=60)
def fetch_mstr_options():
    try:
        mstr = yf.Ticker("MSTR")
        exps = mstr.options
        if not exps:
            return 0, 1.0, None

        chain = mstr.option_chain(exps[0])
        calls = chain.calls
        puts  = chain.puts

        call_vol = calls['volume'].sum() if calls['volume'].sum() > 0 else len(calls)
        put_vol  = puts['volume'].sum() if puts['volume'].sum() > 0 else len(puts)
        pc_ratio = float(put_vol / call_vol) if call_vol > 0 else 1.0

        mstr_data_inner = fetch_mstr_data()
        atm_iv = 0
        if mstr_data_inner:
            p = mstr_data_inner['price']
            hv30 = mstr_data_inner['hv30'] if mstr_data_inner['hv30'] > 0 else 0.85
            calls_v = calls[(calls['impliedVolatility'] > 0.50) & (calls['impliedVolatility'] < 3.00)].copy()
            if not calls_v.empty:
                calls_v['dist'] = abs(calls_v['strike'] - p)
                near_atm = calls_v.sort_values('dist').head(5)
                atm_iv = float(near_atm['impliedVolatility'].median())
                if atm_iv < hv30 * 0.7:
                    atm_iv = hv30
            else:
                atm_iv = hv30

        return atm_iv, pc_ratio, exps[0]
    except:
        return 0, 1.0, None

@st.cache_data(ttl=60)
def fetch_market_price_for_option(ticker_symbol, expiry_date, strike, option_type='call'):
    try:
        obj = yf.Ticker(ticker_symbol)
        exps = obj.options
        if not exps:
            return 0, 0

        try:
            exp_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
            exp_str = exp_dt.strftime("%Y-%m-%d")
        except:
            exp_str = expiry_date

        matched_exp = None
        for e in exps:
            if e == exp_str:
                matched_exp = e
                break
        if matched_exp is None:
            try:
                target = datetime.strptime(exp_str, "%Y-%m-%d")
                closest = min(exps, key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d") - target).days))
                if abs((datetime.strptime(closest, "%Y-%m-%d") - target).days) <= 7:
                    matched_exp = closest
            except:
                pass

        if matched_exp is None:
            return 0, 0

        chain = obj.option_chain(matched_exp)
        df = chain.calls if option_type == 'call' else chain.puts

        df = df.copy()
        df['strike_dist'] = abs(df['strike'] - strike)
        matched = df.sort_values('strike_dist').iloc[0]

        bid = matched['bid'] if pd.notna(matched['bid']) and matched['bid'] > 0 else 0
        ask = matched['ask'] if pd.notna(matched['ask']) and matched['ask'] > 0 else 0
        last = matched['lastPrice'] if pd.notna(matched['lastPrice']) and matched['lastPrice'] > 0 else 0
        iv = matched['impliedVolatility'] if pd.notna(matched['impliedVolatility']) and matched['impliedVolatility'] > 0 else 0

        if bid > 0 and ask > 0:
            market_price = (bid + ask) / 2
        elif last > 0:
            market_price = last
        else:
            market_price = 0

        return market_price, iv
    except:
        return 0, 0

@st.cache_data(ttl=60)
def fetch_beta_mstr_btc():
    try:
        mstr = yf.Ticker("MSTR").history(period="3mo", interval="1d")
        btc  = yf.Ticker("BTC-USD").history(period="3mo", interval="1d")
        if mstr.empty or btc.empty:
            return 0
        mstr.index = mstr.index.tz_localize(None)
        btc.index  = btc.index.tz_localize(None)
        m_ret = mstr['Close'].pct_change().dropna()
        b_ret = btc['Close'].pct_change().dropna()
        combined = pd.concat([m_ret, b_ret], axis=1, join='inner').dropna()
        if len(combined) < 10:
            return 0
        cov = np.cov(combined.iloc[:, 0], combined.iloc[:, 1])[0][1]
        var = np.var(combined.iloc[:, 1])
        return cov / var if var != 0 else 0
    except:
        return 0

@st.cache_data(ttl=300)
def fetch_macro():
    try:
        tnx  = yf.Ticker("^TNX").history(period="5d")
        dxy  = yf.Ticker("DX-Y.NYB").history(period="5d")
        ndx  = yf.Ticker("^NDX").history(period="2d")
        t10y = float(tnx['Close'].iloc[-1]) if not tnx.empty else 0
        dxy_v= float(dxy['Close'].iloc[-1]) if not dxy.empty else 0
        ndx_d= 0
        if not ndx.empty and len(ndx) >= 2:
            ndx_d = (ndx['Close'].iloc[-1] - ndx['Close'].iloc[-2]) / ndx['Close'].iloc[-2] * 100
        return {'t10y': t10y, 'dxy': dxy_v, 'ndx_delta': ndx_d}
    except:
        return {'t10y': 0, 'dxy': 0, 'ndx_delta': 0}

@st.cache_data(ttl=30)
def fetch_funding_rate():
    try:
        url  = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        data = requests.get(url, timeout=5).json()
        return float(data.get("lastFundingRate", 0.0001))
    except:
        return 0.0001

@st.cache_data(ttl=300)
def fetch_fear_greed():
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8).json()
        return int(data["data"][0]["value"])
    except:
        return 50

@st.cache_data(ttl=30)
def fetch_200wma():
    try:
        df = yf.Ticker("BTC-USD").history(period="max", interval="1wk")
        if not df.empty:
            df = df.reset_index()
            df['200WMA'] = df['Close'].rolling(200).mean()
            return float(df['200WMA'].iloc[-1])
        return 0
    except:
        return 0

# ==========================================
# 2. 側邊欄
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ MSTR 財務參數")
    st.caption("修改後自動儲存，刷新保留")

    MSTR_BTC_HOLDINGS = st.number_input("BTC 總持倉量",
        value=st.session_state["MSTR_BTC_HOLDINGS_val"], step=100,
        key="MSTR_BTC_HOLDINGS", on_change=save_params)
    MSTR_AVG_COST = st.number_input("平均買入成本 ($/BTC)",
        value=st.session_state["MSTR_AVG_COST_val"], step=100,
        key="MSTR_AVG_COST", on_change=save_params)

    st.markdown("---")
    st.markdown("**官方 mNAV 參數（FDSO 口徑）**")
    MSTR_BASIC_SHARES = st.number_input("基本流通股數 (Basic)",
        value=st.session_state["MSTR_BASIC_SHARES_val"], step=1000000,
        key="MSTR_BASIC_SHARES", on_change=save_params)
    MSTR_TOTAL_DEBT_M = st.number_input("總債務 Total Debt (百萬$)",
        value=st.session_state["MSTR_TOTAL_DEBT_M_val"], step=100,
        key="MSTR_TOTAL_DEBT_M", on_change=save_params)
    MSTR_TOTAL_PREF_M = st.number_input("優先股 Total Pref (百萬$)",
        value=st.session_state["MSTR_TOTAL_PREF_M_val"], step=100,
        key="MSTR_TOTAL_PREF_M", on_change=save_params)
    MSTR_CASH_RESERVE_M = st.number_input("USD Assets (百萬$)",
        value=st.session_state["MSTR_CASH_RESERVE_M_val"], step=100,
        key="MSTR_CASH_RESERVE_M", on_change=save_params)

    st.markdown("---")
    st.markdown("**FDSO（完全稀釋股數）**")
    MSTR_FDSO = st.number_input("完全稀釋股數 FDSO",
        value=st.session_state["MSTR_FDSO_val"], step=1000000,
        key="MSTR_FDSO", on_change=save_params)

    st.markdown("---")
    st.markdown("**🆘 手動備援**")
    st.caption("當 yfinance 完全失效時，手動輸入 MSTR 股價")
    manual_mstr_price = st.number_input(
        "手動 MSTR 股價 (0 = 不使用)",
        min_value=0.0, max_value=10000.0, value=0.0,
        step=1.0, key="manual_mstr_price"
    )

    st.markdown("---")
    st.caption("📡 數據來源：yfinance + 公開 API")
    st.caption("☁️ 雲端版：市場價自動抓取")

    btc_price, btc_delta = fetch_btc_price()
    mstr_data  = fetch_mstr_data()
    
    # 若 yfinance 完全失效，使用手動股價
    if mstr_data is None and manual_mstr_price > 0:
        mstr_price = manual_mstr_price
        st.warning(f"⚠️ yfinance 失效，使用手動輸入股價 ${mstr_price:.2f}")
        # 用一個假的 mstr_data 讓後續計算能跑
        mstr_data = {
            'price': mstr_price, 'rsi': 50.0,
            'ma20': mstr_price, 'ma60': mstr_price,
            'bb_upper': mstr_price * 1.1, 'bb_lower': mstr_price * 0.9,
            'hv30': 0.85, 'hist': pd.DataFrame()
        }
    elif mstr_data:
        mstr_price = mstr_data['price']
    else:
        mstr_price = 0

    funding    = fetch_funding_rate()
    fng        = fetch_fear_greed()
    macro      = fetch_macro()
    ma200w     = fetch_200wma()
    beta_btc   = fetch_beta_mstr_btc()
    atm_iv, pc_ratio, next_exp = fetch_mstr_options()

    if btc_price > 0 and mstr_price > 0:
        usd_assets_m        = MSTR_CASH_RESERVE_M
        net_btc             = MSTR_BTC_HOLDINGS - (MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - usd_assets_m) * 1e6 / btc_price
        net_bps_usd         = (net_btc / MSTR_FDSO) * btc_price if MSTR_FDSO > 0 else 0
        official_mnav       = mstr_price / net_bps_usd if net_bps_usd > 0 else 0

        net_bps_basic_usd   = (net_btc / MSTR_BASIC_SHARES) * btc_price if MSTR_BASIC_SHARES > 0 else 0
        basic_mnav          = mstr_price / net_bps_basic_usd if net_bps_basic_usd > 0 else 0

        btc_reserve_m       = btc_price * MSTR_BTC_HOLDINGS / 1e6
        net_reserve_m       = btc_reserve_m + usd_assets_m - MSTR_TOTAL_DEBT_M - MSTR_TOTAL_PREF_M
        net_claims_m        = MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - MSTR_CASH_RESERVE_M
        claims_btc          = net_claims_m * 1e6 / btc_price
        common_equity_btc   = MSTR_BTC_HOLDINGS - claims_btc
        net_bps_sats        = int(net_btc / MSTR_FDSO * 1e8) if MSTR_FDSO > 0 else 0
        drag_pct            = claims_btc / MSTR_BTC_HOLDINGS * 100
    else:
        official_mnav = basic_mnav = net_bps_usd = net_bps_basic_usd = 0
        btc_reserve_m = net_reserve_m = net_btc = 0
        net_claims_m = claims_btc = common_equity_btc = net_bps_sats = drag_pct = 0

    if btc_price > 0:
        pnl_usd   = (btc_price - MSTR_AVG_COST) * MSTR_BTC_HOLDINGS
        pnl_color = "green" if pnl_usd >= 0 else "red"
        st.markdown(f"💼 BTC持倉損益：<span style='color:{pnl_color};font-weight:bold;'>${pnl_usd/1e9:.2f}B</span>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📈 即時 mNAV")
    oc = "#f3ba2f" if official_mnav >= 1 else "#0ecb81"
    bc = "#f3ba2f" if basic_mnav >= 1 else "#0ecb81"
    st.markdown(f"""
        <div style="background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:10px;color:#848e9c;">🏛️ 官方 mNAV（FDSO 口徑）</div>
            <div style="font-size:24px;font-weight:800;color:{oc};font-family:monospace;">{official_mnav:.3f}x</div>
            <div style="font-size:10px;color:#848e9c;">股價 ${mstr_price:.2f} ÷ Net BPS ${net_bps_usd:.2f}</div>
        </div>
        <div style="background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:10px;color:#848e9c;">🔬 Basic mNAV（基本流通股口徑）</div>
            <div style="font-size:24px;font-weight:800;color:{bc};font-family:monospace;">{basic_mnav:.3f}x</div>
            <div style="font-size:10px;color:#848e9c;">股價 ${mstr_price:.2f} ÷ Basic BPS ${net_bps_basic_usd:.2f}</div>
            <div style="font-size:10px;color:#f6465d;">反身性風險警示：Basic mNAV 越低，越接近 1.0 警戒線</div>
        </div>
    """, unsafe_allow_html=True)

# ==========================================
# 3. 主頁面
# ==========================================
st.markdown(f"""
<div style="padding:10px 0 20px 0;border-bottom:1px solid #2b3139;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:700;color:#eaecef;">📡 MSTR 股價監控戰情室（雲端版）</div>
    <div style="font-size:12px;color:#848e9c;margin-top:4px;">更新時間：{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')} 台北時間</div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] { background-color: #0b0e11 !important; color: #eaecef !important; font-family: 'SF Pro Display', -apple-system, sans-serif; }
[data-testid="stHeader"] { background: rgba(0,0,0,0); }
[data-testid="stSidebar"] { background-color: #161b22 !important; }
footer { visibility: hidden; }
.kpi { background:#161b22; border:1px solid #2b3139; border-radius:8px; padding:14px 16px; margin-bottom:8px; }
.kpi-label { font-size:10px; color:#848e9c; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
.kpi-value { font-size:20px; font-weight:700; font-family:monospace; }
.kpi-sub   { font-size:10px; color:#848e9c; margin-top:3px; }
.sig-bull  { background:#0d2818; border-left:4px solid #238636; border-radius:6px; padding:12px 14px; margin-bottom:8px; }
.sig-bear  { background:#2d1517; border-left:4px solid #da3633; border-radius:6px; padding:12px 14px; margin-bottom:8px; }
.sig-neut  { background:#1c1f26; border-left:4px solid #6e7681; border-radius:6px; padding:12px 14px; margin-bottom:8px; }
.sig-t { font-size:12px; font-weight:700; margin-bottom:4px; }
.sig-d { font-size:11px; color:#8b949e; line-height:1.5; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. KPI 列
# ==========================================
st.markdown("#### 📊 核心即時指標")
k1,k2,k3,k4,k5,k6 = st.columns(6)

def kpi(col, label, value, sub="", color="#eaecef"):
    col.markdown(f"""<div class="kpi">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value" style="color:{color};">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)

mstr_chg_color = "#238636" if mstr_price >= (mstr_data['ma20'] if mstr_data else 0) else "#da3633"
btc_chg_color  = "#238636" if btc_delta >= 0 else "#da3633"
rsi_color = "#da3633" if mstr_data and mstr_data['rsi'] > 70 else "#238636" if mstr_data and mstr_data['rsi'] < 30 else "#f0883e"
iv_color  = "#f0883e" if atm_iv > 0 else "#848e9c"
fng_color = "#238636" if fng <= 30 else "#da3633" if fng >= 70 else "#848e9c"

kpi(k1, "MSTR 股價", f"${mstr_price:.2f}" if mstr_price > 0 else "N/A",
    f"MA20 ${mstr_data['ma20']:.2f} | MA60 ${mstr_data['ma60']:.2f}" if mstr_data and not mstr_data['hist'].empty else "數據載入失敗",
    mstr_chg_color)
kpi(k2, "BTC 即時價格", f"${btc_price:,.0f}", f"24H {btc_delta:+.2f}%", btc_chg_color)
kpi(k3, "RSI (14)", f"{mstr_data['rsi']:.1f}" if mstr_data and not mstr_data['hist'].empty else "N/A", "超買 >70 | 超賣 <30", rsi_color)
kpi(k4, "隱含波動率 IV", f"{atm_iv*100:.1f}%" if atm_iv > 0 else "N/A",
    f"HV30 {mstr_data['hv30']*100:.1f}% | IV/HV {atm_iv/mstr_data['hv30']:.2f}x" if mstr_data and mstr_data['hv30'] > 0 and atm_iv > 0 else "", iv_color)
kpi(k5, "Put/Call Ratio", f"{pc_ratio:.2f}" if pc_ratio else "N/A", ">1.0 市場偏空 | <0.7 市場偏多",
    "#da3633" if pc_ratio and pc_ratio > 1.0 else "#238636" if pc_ratio and pc_ratio < 0.7 else "#848e9c")
kpi(k6, "恐懼貪婪指數", f"{fng}/100",
    "😱極恐" if fng<=25 else "😟恐懼" if fng<=45 else "😐中性" if fng<=55 else "😏貪婪" if fng<=75 else "🤑極貪", fng_color)

k7,k8,k9,k10,k11,k12 = st.columns(6)
kpi(k7, "MSTR/BTC Beta", f"{beta_btc:.2f}x", f"BTC漲1%→MSTR預期{beta_btc:.2f}%", "#a5d6ff")
kpi(k8, "BTC 資金費率", f"{funding*100:+.4f}%",
    "空頭過熱" if funding < -0.0002 else "多空平衡" if abs(funding) < 0.0002 else "多頭過熱",
    "#238636" if funding < -0.0002 else "#da3633" if funding > 0.0005 else "#848e9c")
kpi(k9, "美債10年殖利率", f"{macro['t10y']:.2f}%", "高→估值壓縮" if macro['t10y'] > 4.5 else "低→估值擴張",
    "#da3633" if macro['t10y'] > 4.5 else "#238636")
kpi(k10, "美元指數 DXY", f"{macro['dxy']:.2f}", "強→BTC承壓" if macro['dxy'] > 103 else "弱→BTC助漲",
    "#da3633" if macro['dxy'] > 103 else "#238636")
kpi(k11, "納斯達克 NDX", f"{macro['ndx_delta']:+.2f}%", "科技股情緒參考",
    "#238636" if macro['ndx_delta'] >= 0 else "#da3633")

dist_200w = (btc_price - ma200w) / ma200w * 100 if ma200w > 0 else 0
kpi(k12, "BTC 200週均線", f"${ma200w:,.0f}", f"現價距離 {dist_200w:+.1f}%",
    "#da3633" if dist_200w < 10 else "#238636")

# ==========================================
# 5. 圖表區
# ==========================================
st.markdown("---")
col_chart, col_sig = st.columns([1.6, 1])

with col_chart:
    st.markdown("#### 📈 MSTR 6個月股價走勢")
    if mstr_data and not mstr_data['hist'].empty:
        h = mstr_data['hist'].copy()
        h['MA20'] = h['Close'].rolling(20).mean()
        h['MA60'] = h['Close'].rolling(60).mean()
        h['BB_U'] = h['Close'].rolling(20).mean() + 2*h['Close'].rolling(20).std()
        h['BB_L'] = h['Close'].rolling(20).mean() - 2*h['Close'].rolling(20).std()

        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=h.index, open=h['Open'], high=h['High'], low=h['Low'], close=h['Close'],
            name='MSTR', increasing_line_color='#238636', decreasing_line_color='#da3633'))
        fig.add_trace(go.Scatter(x=h.index, y=h['MA20'], name='MA20', line=dict(color='#f0883e', width=1.2)))
        fig.add_trace(go.Scatter(x=h.index, y=h['MA60'], name='MA60', line=dict(color='#a5d6ff', width=1.2, dash='dash')))
        fig.add_trace(go.Scatter(x=h.index, y=h['BB_U'], name='BB上軌', line=dict(color='#6e7681', width=0.8, dash='dot')))
        fig.add_trace(go.Scatter(x=h.index, y=h['BB_L'], name='BB下軌', line=dict(color='#6e7681', width=0.8, dash='dot'), fill='tonexty', fillcolor='rgba(110,118,129,0.05)'))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, tickfont=dict(color='#848e9c'), rangeslider_visible=False),
            yaxis=dict(showgrid=True, gridcolor='#21262d', tickfont=dict(color='#848e9c')),
            legend=dict(font=dict(color='#848e9c', size=10), orientation='h', y=1.05),
            height=380, margin=dict(l=0,r=0,t=30,b=0))
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    else:
        st.warning("⚠️ MSTR 歷史數據載入失敗。若 yfinance 失效，請在側邊欄手動輸入股價。")

with col_sig:
    st.markdown("#### 🚦 多維訊號判讀")
    if mstr_data and not mstr_data['hist'].empty:
        rsi_val = mstr_data['rsi']
        if rsi_val > 70:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 RSI 超買（{rsi_val:.1f}）</div><div class="sig-d">短期漲幅過大，注意回調風險。</div></div>', unsafe_allow_html=True)
        elif rsi_val < 30:
            st.markdown(f'<div class="sig-bull"><div class="sig-t" style="color:#238636;">🟢 RSI 超賣（{rsi_val:.1f}）</div><div class="sig-d">短期跌幅過大，反彈機率上升。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ RSI 中性（{rsi_val:.1f}）</div><div class="sig-d">動能正常。</div></div>', unsafe_allow_html=True)

    if official_mnav > 0:
        if official_mnav > 1.5:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 官方 mNAV 偏高（{official_mnav:.3f}x）</div><div class="sig-d">股價溢價過高，泡沫風險上升。</div></div>', unsafe_allow_html=True)
        elif official_mnav < 1.05:
            st.markdown(f'<div class="sig-bull"><div class="sig-t" style="color:#238636;">🟢 官方 mNAV 接近清算價值（{official_mnav:.3f}x）</div><div class="sig-d">股價接近每股真實BTC淨值，歷史上為優質買點。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ 官方 mNAV 正常（{official_mnav:.3f}x）</div><div class="sig-d">溢價在合理區間。</div></div>', unsafe_allow_html=True)

    if macro['t10y'] > 4.5:
        st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 美債殖利率偏高（{macro["t10y"]:.2f}%）</div><div class="sig-d">高利率環境壓縮成長股估值。</div></div>', unsafe_allow_html=True)
    if macro['dxy'] > 103:
        st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 美元偏強（DXY {macro["dxy"]:.2f}）</div><div class="sig-d">強勢美元對 BTC 形成壓力。</div></div>', unsafe_allow_html=True)

# ==========================================
# 7. 選擇權鏈
# ==========================================
st.markdown("---")
st.markdown("#### 📋 MSTR 選擇權鏈（ATM 附近，最近到期）")
try:
    if mstr_price > 0:
        mstr_obj = yf.Ticker("MSTR")
        exps = mstr_obj.options
        if exps:
            exp_choice = st.selectbox("選擇到期日", exps[:6], index=0)
            chain = mstr_obj.option_chain(exp_choice)
            calls = chain.calls.copy()
            calls['dist'] = abs(calls['strike'] - mstr_price)
            atm_calls = calls.sort_values('dist').head(10).sort_values('strike').reset_index(drop=True)
            atm_calls['ATM'] = atm_calls['strike'].apply(lambda x: '← ATM' if abs(x - mstr_price) == atm_calls['dist'].min() else '')

            iv_fallback = mstr_data['hv30'] if mstr_data and mstr_data['hv30'] > 0 else 0.8
            atm_calls['IV顯示'] = atm_calls['impliedVolatility'].apply(
                lambda x: f"{x*100:.1f}%" if x > 0 else f"~{iv_fallback*100:.1f}%(HV)")

            disp = pd.DataFrame()
            disp['履約價'] = atm_calls['strike'].apply(lambda x: f"${x:.0f}")
            disp['最新成交'] = atm_calls['lastPrice'].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
            disp['Bid'] = atm_calls['bid'].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
            disp['Ask'] = atm_calls['ask'].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
            disp['IV'] = atm_calls['IV顯示']
            disp['成交量'] = atm_calls['volume'].apply(lambda x: f"{int(x):,}" if x > 0 else "—")
            disp['未平倉量'] = atm_calls['openInterest'].apply(lambda x: f"{int(x):,}" if x > 0 else "—")
            disp[''] = atm_calls['ATM']

            st.caption(f"到期日：{exp_choice} | MSTR 現價 ${mstr_price:.2f} | Call 選擇權 | 數據來源：yfinance")
            st.dataframe(disp, use_container_width=True, hide_index=True)
except Exception as e:
    st.warning(f"選擇權鏈載入失敗：{e}")

# ==========================================
# 7b. 備兌買權部位監控與策略建議（雲端版：自動抓取市場價）
# ==========================================
st.markdown("---")
st.markdown("## 🎯 備兌買權部位監控與平倉策略")
st.caption("☁️ 雲端版：市場價自動從 yfinance 期權鏈抓取，若抓不到則用手動備援值")

with st.expander("✏️ 編輯部位（新增/修改/停用）"):
    st.caption("⚠️ net_cash = 這筆合約從開倉至今的歷史淨收入總額。市場價 = 備援值（yfinance 抓不到時使用）。")
    positions = st.session_state["cc_positions"]
    for i, pos in enumerate(positions):
        c1,c2,c3,c4,c5,c6,c7 = st.columns([2,1.2,1.5,1,1.2,1.2,0.8])
        positions[i]["label"]        = c1.text_input("名稱", pos["label"], key=f"cc_label_{i}")
        positions[i]["strike"]       = c2.number_input("履約價$",
            min_value=0.0, max_value=10000.0, value=float(pos["strike"]),
            step=5.0, key=f"cc_k_{i}")
        positions[i]["expiry"]       = c3.text_input("到期(YYYY-MM-DD)", pos["expiry"], key=f"cc_exp_{i}")
        positions[i]["contracts"]    = c4.number_input("口數",
            min_value=0, max_value=10000, value=int(pos["contracts"]),
            step=1, key=f"cc_ct_{i}")
        positions[i]["net_cash"]     = c5.number_input("歷史淨收入$",
            min_value=-100000.0, max_value=1000000.0, value=float(pos["net_cash"]),
            step=10.0, key=f"cc_cash_{i}")
        positions[i]["market_price"] = c6.number_input("備援市價$",
            min_value=0.0, max_value=10000.0, value=float(pos.get("market_price", 0.0)),
            step=0.1, key=f"cc_mkt_{i}")
        positions[i]["active"]       = c7.checkbox("啟用", pos["active"], key=f"cc_act_{i}")
    if st.button("➕ 新增部位"):
        st.session_state["cc_positions"].append({
            "id": len(positions)+1, "label": "新部位",
            "strike": 200.0, "expiry": "2025-12-19",
            "contracts": 1, "net_cash": 0.0, "market_price": 0.0,
            "ticker": "MSTR", "active": True
        })
        st.rerun()
    st.session_state["cc_positions"] = positions

r_rf = 0.045
positions = [p for p in st.session_state["cc_positions"] if p["active"]]

if mstr_price > 0 and positions:
    rows_cc = []
    for pos in positions:
        try:
            exp_dt = datetime.strptime(pos["expiry"], "%Y-%m-%d")
            today  = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            days_left = max(0, (exp_dt - today).days)
            T = max(days_left, 1) / 365
        except:
            days_left = 30
            T = 30/365

        auto_market_price = 0
        auto_iv = 0
        try:
            auto_market_price, auto_iv = fetch_market_price_for_option(
                pos["ticker"], pos["expiry"], pos["strike"], 'call'
            )
        except:
            pass

        manual_market_price = pos.get("market_price", 0.0)
        if auto_market_price > 0:
            market_price = auto_market_price
            price_source = "自動"
        elif manual_market_price > 0:
            market_price = manual_market_price
            price_source = "手動"
        else:
            market_price = 0
            price_source = "無"

        if market_price > 0 and T > 0:
            iv_from_market = implied_vol_from_price(mstr_price, pos["strike"], T, r_rf, market_price)
            if iv_from_market > 0:
                iv_use = iv_from_market
            else:
                iv_use = atm_iv if atm_iv > 0 else (mstr_data['hv30'] if mstr_data and mstr_data['hv30'] > 0 else 0.85)
        else:
            iv_use = atm_iv if atm_iv > 0 else (mstr_data['hv30'] if mstr_data and mstr_data['hv30'] > 0 else 0.85)
        if iv_use <= 0: iv_use = 0.85

        iv_valid = iv_use >= 0.50

        if iv_valid:
            bs_price, delta, theta, prob_itm = bs_call(mstr_price, pos["strike"], T, r_rf, iv_use)
            delta_disp = f"{delta:.2f}"
            prob_disp  = f"{prob_itm*100:.1f}%"
            theta_disp = f"${theta:.3f}"
        else:
            bs_price = delta = theta = prob_itm = 0
            delta_disp = prob_disp = theta_disp = "—"

        market_disp = f"${market_price:.2f}" if market_price > 0 else "—"

        net_cash    = pos["net_cash"]
        buyback_est = market_price * 100 * pos["contracts"] if market_price > 0 else 0
        total_pnl   = net_cash - buyback_est
        pnl_per     = total_pnl / pos["contracts"] if pos["contracts"] > 0 else 0

        if iv_valid:
            if prob_itm > 0.7 or days_left <= 14: urgency = "🔴 緊急"
            elif prob_itm > 0.4 or days_left <= 30: urgency = "🟡 注意"
            else: urgency = "🟢 安全"
        else:
            urgency = "⚠️ IV異常"

        rows_cc.append({
            "部位": pos["label"], "履約價": f"${pos['strike']:.0f}", "到期": pos["expiry"],
            "剩餘天數": f"{days_left}天", "口數": pos["contracts"],
            "市場價": market_disp, "來源": price_source,
            "Delta": delta_disp, "被指派機率": prob_disp, "Theta/天": theta_disp,
            "每口P&L": f"${pnl_per:+.0f}", "總P&L": f"${total_pnl:+,.0f}", "狀態": urgency,
        })

    df_cc = pd.DataFrame(rows_cc)
    st.dataframe(df_cc, use_container_width=True, hide_index=True)

    total_buyback = sum(
        (fetch_market_price_for_option(p["ticker"], p["expiry"], p["strike"], 'call')[0] or p.get("market_price", 0.0)) * 100 * p["contracts"]
        for p in positions
    )
    total_net_cash = sum(p["net_cash"] for p in positions)
    net_pnl_all = total_net_cash - total_buyback if total_buyback > 0 else 0

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("全部平倉估算成本", f"${total_buyback:,.0f}" if total_buyback > 0 else "—")
    col_b.metric("這批合約歷史淨收入", f"${total_net_cash:,.0f}")
    col_c.metric("淨損益（正=獲利）", f"${net_pnl_all:+,.0f}" if total_buyback > 0 else "—",
                 delta="獲利" if net_pnl_all >= 0 else "虧損" if total_buyback > 0 else "")

# ==========================================
# 8. 官方 mNAV 壓力測試模擬表
# ==========================================
st.markdown("---")
st.subheader("📊 MSTR 官方 mNAV 股價真實價值壓力測試模擬")
st.markdown(f"基於 **{MSTR_BTC_HOLDINGS:,} BTC** 持倉，官方 mNAV 計算法（FDSO 口徑）：")

sim_prices = list(range(50000, 200001, 10000))
rows = []
for p in sim_prices:
    sim_net_btc     = MSTR_BTC_HOLDINGS - (MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - MSTR_CASH_RESERVE_M) * 1e6 / p
    sim_net_bps_usd = (sim_net_btc / MSTR_FDSO) * p if MSTR_FDSO > 0 else 0
    sim_net_bps_sats = sim_net_btc / MSTR_FDSO * 1e8 if MSTR_FDSO > 0 else 0
    sim_drag        = (MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - MSTR_CASH_RESERVE_M) * 1e6 / p / MSTR_BTC_HOLDINGS * 100
    rows.append({
        "BTC 模擬價格": f"${p:,.0f}", "每股 Net BPS（sats）": f"{sim_net_bps_sats:,.0f}",
        "每股 Net BPS（USD）": f"${sim_net_bps_usd:,.2f}", "Drag（債務侵蝕率）": f"{sim_drag:.1f}%",
        "1.0x 清算價值": f"${sim_net_bps_usd * 1.0:,.2f}", "1.1x": f"${sim_net_bps_usd * 1.1:,.2f}",
        "1.2x 合理防線": f"${sim_net_bps_usd * 1.2:,.2f}", "1.3x": f"${sim_net_bps_usd * 1.3:,.2f}",
        "1.4x": f"${sim_net_bps_usd * 1.4:,.2f}", "1.5x": f"${sim_net_bps_usd * 1.5:,.2f}",
        "1.6x 泡沫警戒": f"${sim_net_bps_usd * 1.6:,.2f}",
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
