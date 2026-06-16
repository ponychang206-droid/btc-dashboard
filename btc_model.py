import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo
from binance.cm_futures import CMFutures

# ==========================================
# 0. 網頁全域設定
# ==========================================
st.set_page_config(
    page_title="BTC 抄底監控戰情室",
    layout="wide",
    initial_sidebar_state="expanded"
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# ==========================================
# 1. 數據抓取模組
# ==========================================
@st.cache_data(ttl=5)
def fetch_binance_ticker():
    try:
        btc = yf.Ticker("BTC-USD")
        df = btc.history(period="2d", interval="5m")
        if not df.empty:
            last_price = float(df['Close'].iloc[-1])
            df_24h = btc.history(period="1d", interval="1m")
            high_price = float(df_24h['High'].max()) if not df_24h.empty else last_price
            low_price = float(df_24h['Low'].min()) if not df_24h.empty else last_price
            prev_close = float(df['Close'].iloc[0])
            delta_pct = ((last_price - prev_close) / prev_close) * 100
            return {'price': last_price, 'high': high_price, 'low': low_price, 'delta': delta_pct}
        return None
    except: return None

@st.cache_data(ttl=5)
def fetch_funding_rate():
    try:
        cm_client = CMFutures()
        res = cm_client.premium_index(symbol="BTCUSD_PERP")
        if isinstance(res, list) and len(res) > 0: return float(res[0].get('lastFundingRate', 0.0001))
        return 0.0001
    except: return 0.0001

@st.cache_data(ttl=30)
def fetch_historical_data():
    try:
        btc = yf.Ticker("BTC-USD")
        df_d = btc.history(period="100d", interval="1d")
        daily_closes = df_d['Close'].tolist() if not df_d.empty else []
        df_w = btc.history(period="max", interval="1wk")
        if not df_w.empty:
            df_w = df_w.reset_index()
            df_w['200WMA'] = df_w['Close'].rolling(window=200).mean()
        return daily_closes, df_w
    except: return [], pd.DataFrame()

@st.cache_data(ttl=30)
def fetch_fear_greed():
    try:
        vix = yf.Ticker("^VIX")
        vix_df = vix.history(period="1d")
        if not vix_df.empty:
            vix_price = float(vix_df['Close'].iloc[-1])
            return max(10, min(90, int(100 - (vix_price * 2))))
        return 50
    except: return 50

@st.cache_data(ttl=60)
def fetch_mstr_premium():
    try:
        mstr = yf.Ticker("MSTR")
        df_mstr = mstr.history(period="1d", interval="1m")
        if not df_mstr.empty: return float(df_mstr['Close'].iloc[-1])
        return None
    except: return None

# ==========================================
# 2. 參數與計算引擎
# ==========================================
# 固定數據 (來自用戶輸入)
MSTR_BTC_HOLDINGS = 846842
MSTR_SHARES_OUTSTANDING = 386052000
MSTR_AVG_COST = 75656
MSTR_NET_DEBT = 4500000000
DILUTED_SHARES = 400000000

# 即時數據
ticker_data = fetch_binance_ticker()
btc_price = ticker_data['price'] if ticker_data else 0
funding_rate = fetch_funding_rate()
daily_closes, df_weekly = fetch_historical_data()
fng_value = fetch_fear_greed()
mstr_live_price = fetch_mstr_premium()

BTC_PER_SHARE = MSTR_BTC_HOLDINGS / MSTR_SHARES_OUTSTANDING
total_score, s1, s2, s3, s4, s5, s6, s7, s8, s9 = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
price_delta_str = f"{ticker_data['delta']:.2f}%" if ticker_data else "0.00%"
ma200_w_current = 0.0
mstr_premium_rate = 1.20

if ticker_data:
    p_range = ticker_data['high'] - ticker_data['low']
    s1 = (((ticker_data['high'] - btc_price) / p_range) * 5.0) if p_range > 0 else 2.5
    bias = (btc_price - np.mean(daily_closes[-60:])) / np.mean(daily_closes[-60:]) if len(daily_closes) >= 60 else 0
    s2 = max(0.0, min(10.0, (0.0 - bias) / 0.20 * 10.0))
    r14 = (btc_price - daily_closes[-14]) / daily_closes[-14] if len(daily_closes) >= 14 else 0
    s3 = max(0.0, min(5.0, (0.0 - r14) / 0.15 * 5.0))
    s4 = max(0.0, min(5.0, (abs(ticker_data['delta']) / 5.0) * 5.0)) if ticker_data['delta'] < 0 else 0.0
    s5 = max(0.0, min(15.0, ((40.0 - float(fng_value)) / 30.0) * 15.0))
    s6 = max(0.0, min(15.0, ((0.0001 - funding_rate) / 0.0004) * 15.0))
    if mstr_live_price:
        estimated_nav = (btc_price * BTC_PER_SHARE)
        mstr_premium_rate = mstr_live_price / estimated_nav if estimated_nav > 0 else 1.20
        s7 = max(0.0, min(15.0, ((2.5 - mstr_premium_rate) / 1.5) * 15.0))
    if not df_weekly.empty and len(df_weekly) >= 200:
        ma200_w_current = float(df_weekly.iloc[-1]['200WMA'])
        dist_200w = (btc_price - ma200_w_current) / ma200_w_current
        s8 = max(0.0, min(20.0, ((0.05 - dist_200w) / 0.10) * 20.0))
    last_halving = datetime(2024, 4, 20, tzinfo=TAIPEI_TZ)
    days_since_halving = (datetime.now(TAIPEI_TZ) - last_halving).days
    cycle_progress = (days_since_halving % 1460) / 1460
    s9 = max(0.0, min(5.0, (1.0 - cycle_progress) * 10.0)) if 500 <= days_since_halving % 1460 <= 800 else max(5.0, min(10.0, cycle_progress * 10.0))
    total_score = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8 + s9

# ==========================================
# 3. 顯示介面
# ==========================================
st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"] { background-color: #0b0e11; color: #eaecef; }
    .metric-card { background: linear-gradient(135deg, #181a20 0%, #1e222b 100%); border: 1px solid #2b3139; border-radius: 12px; padding: 16px; margin-bottom: 12px; }
    .score-display { font-size: 48px; font-weight: 800; color: #f3ba2f; }
    </style>
""", unsafe_allow_html=True)

st.markdown(f"## 🔮 BTC 9 因子抄底監控看板")
st.write(f"最後更新：{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

col_left, col_right = st.columns([1, 1])

with col_left:
    st.metric("BTC 現價", f"${btc_price:,.2f}", f"{price_delta_str}")
    fig_gauge = go.Figure(go.Indicator(mode="gauge+number", value=total_score, gauge={'axis': {'range': [0, 100]}}))
    st.plotly_chart(fig_gauge, use_container_width=True)

with col_right:
    st.markdown(f"<div class='score-display'>{total_score:.1f} / 100 分</div>", unsafe_allow_html=True)
    st.write("得分 > 55 分：考慮介入區間")

# 壓力測試模組
st.subheader("📊 MSTR 全面稀釋清算價值壓力測試")
sim_btc_prices = [70000, 100000, 150000]
rows = []
for p in sim_btc_prices:
    sim_nav_per_share = (MSTR_BTC_HOLDINGS * p - MSTR_NET_DEBT) / DILUTED_SHARES
    rows.append({"BTC 價": f"${p:,.0f}", "NAV 地板": f"${sim_nav_per_share:,.2f}", "1.2x 防線": f"${sim_nav_per_share*1.2:,.2f}"})
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
