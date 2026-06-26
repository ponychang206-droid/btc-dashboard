import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

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
# Session State 初始化
# 只在第一次執行時設定預設值，之後永久保留使用者修改的數值
# ==========================================
DEFAULTS = {
    "MSTR_BTC_HOLDINGS":     846842,    # BTC 總持倉量
    "MSTR_AVG_COST":         75656,     # 歷史平均買入成本 ($/BTC)
    "MSTR_BASIC_SHARES":     356320000, # 基本流通股數 (Basic Shares Outstanding)
    "MSTR_TOTAL_DEBT_M":     6714,      # 總債務 (百萬美元)
    "MSTR_TOTAL_PREF_M":     15475,     # 優先股總額 (百萬美元)
    "MSTR_CASH_RESERVE_M":   1100,      # 美元現金儲備 (百萬美元)
    "MSTR_ADSO":             386052000, # 完全稀釋股數 (Assumed Diluted Shares Outstanding)
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ==========================================
# 1. 數據抓取模組
# ==========================================
@st.cache_data(ttl=5)
def fetch_btc_ticker():
    try:
        btc = yf.Ticker("BTC-USD")
        df = btc.history(period="2d", interval="5m")
        if not df.empty:
            last_price = float(df['Close'].iloc[-1])
            df_24h = btc.history(period="1d", interval="1m")
            high_price = float(df_24h['High'].max()) if not df_24h.empty else last_price
            low_price  = float(df_24h['Low'].min())  if not df_24h.empty else last_price
            prev_close = float(df['Close'].iloc[0])
            delta_pct  = ((last_price - prev_close) / prev_close) * 100
            return {'price': last_price, 'high': high_price, 'low': low_price, 'delta': delta_pct}
        return None
    except:
        return None

@st.cache_data(ttl=30)
def fetch_funding_rate():
    """
    改用 Binance USDT-M Futures 公開 REST API
    BTCUSDT 永續合約才是市場最主流的流動性指標
    endpoint: https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT
    """
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        return float(data.get("lastFundingRate", 0.0001))
    except:
        # 備援：嘗試 Binance 幣本位合約
        try:
            url2 = "https://dapi.binance.com/dapi/v1/premiumIndex?symbol=BTCUSD_PERP"
            resp2 = requests.get(url2, timeout=5)
            data2 = resp2.json()
            if isinstance(data2, list) and len(data2) > 0:
                return float(data2[0].get("lastFundingRate", 0.0001))
        except:
            pass
        return 0.0001

@st.cache_data(ttl=300)
def fetch_fear_greed():
    """
    改用 Alternative.me 免費公開 API
    真正的加密市場恐懼貪婪指數，無需 API Key，不被 Cloudflare 封鎖
    endpoint: https://api.alternative.me/fng/?limit=1
    回傳 0 (極度恐懼) ~ 100 (極度貪婪)
    """
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        resp = requests.get(url, timeout=8)
        data = resp.json()
        value = int(data["data"][0]["value"])
        return value
    except:
        # 備援：用 VIX 反向推算
        try:
            vix = yf.Ticker("^VIX")
            vix_df = vix.history(period="1d")
            if not vix_df.empty:
                vix_price = float(vix_df['Close'].iloc[-1])
                return max(10, min(90, int(100 - (vix_price * 2))))
        except:
            pass
        return 50

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
    except:
        return [], pd.DataFrame()

@st.cache_data(ttl=30)
def fetch_mstr_price():
    try:
        mstr = yf.Ticker("MSTR")
        df_mstr = mstr.history(period="1d", interval="1m")
        if not df_mstr.empty:
            return float(df_mstr['Close'].iloc[-1])
        return None
    except:
        return None

# ==========================================
# 2. 側邊欄控制面板
# ==========================================
with st.sidebar:
    st.markdown("### 🔮 戰情室切換")
    page = st.radio("請選擇檢視視角：", ["直男量化經理人版", "文元專屬：能不能買包包版"], index=0)
    st.markdown("---")

    # ── 基本持倉參數 ──────────────────────────────────────
    st.markdown("### 📦 MSTR 基本持倉參數")
    MSTR_BTC_HOLDINGS = st.number_input(
        "BTC 總持倉量",
        value=st.session_state["MSTR_BTC_HOLDINGS"], step=100,
        key="MSTR_BTC_HOLDINGS"
    )
    MSTR_AVG_COST = st.number_input(
        "歷史平均買入成本 ($ / BTC)",
        value=st.session_state["MSTR_AVG_COST"], step=100,
        key="MSTR_AVG_COST"
    )

    st.markdown("---")

    # ── 官方 mNAV 參數 ────────────────────────────────────
    st.markdown("### 📊 官方 mNAV 參數")
    st.caption("公式：(基本市值 + 總債務 + 優先股 − 現金) ÷ BTC持倉市值")
    MSTR_BASIC_SHARES = st.number_input(
        "基本流通股數 (Basic Shares Outstanding)",
        value=st.session_state["MSTR_BASIC_SHARES"], step=1000000,
        key="MSTR_BASIC_SHARES"
    )
    MSTR_TOTAL_DEBT_M = st.number_input(
        "總債務 Total Debt（百萬美元）",
        value=st.session_state["MSTR_TOTAL_DEBT_M"], step=100,
        key="MSTR_TOTAL_DEBT_M"
    )
    MSTR_TOTAL_PREF_M = st.number_input(
        "優先股總額 Total Pref（百萬美元）",
        value=st.session_state["MSTR_TOTAL_PREF_M"], step=100,
        key="MSTR_TOTAL_PREF_M"
    )
    MSTR_CASH_RESERVE_M = st.number_input(
        "美元現金儲備 USD Cash（百萬美元）",
        value=st.session_state["MSTR_CASH_RESERVE_M"], step=100,
        key="MSTR_CASH_RESERVE_M"
    )

    st.markdown("---")

    # ── CEBE mNAV 額外參數 ────────────────────────────────
    st.markdown("### 🔬 CEBE mNAV 參數")
    st.caption("公式：股價 ÷ [(BTC市值 − 優先股 − 總債務) ÷ 完全稀釋股數]")
    MSTR_ADSO = st.number_input(
        "完全稀釋股數 ADSO",
        value=st.session_state["MSTR_ADSO"], step=1000000,
        key="MSTR_ADSO"
    )

    st.markdown("---")

    # ── 即時數據抓取 ──────────────────────────────────────
    ticker_data = fetch_btc_ticker()
    btc_price   = ticker_data['price'] if ticker_data else 0
    mstr_price  = fetch_mstr_price()

    # BTC 持倉損益
    if btc_price > 0:
        current_pnl_usd = (btc_price - MSTR_AVG_COST) * MSTR_BTC_HOLDINGS
        pnl_billion     = current_pnl_usd / 1e9
        pnl_color       = "green" if current_pnl_usd >= 0 else "red"
        st.markdown(
            f"💼 BTC持倉損益：<span style='color:{pnl_color}; font-weight:bold;'>${pnl_billion:.2f} B USD</span>",
            unsafe_allow_html=True
        )

    # ── 即時 mNAV 計算與顯示 ──────────────────────────────
    if btc_price > 0 and mstr_price:
        btc_reserve_m  = (btc_price * MSTR_BTC_HOLDINGS) / 1e6
        basic_mktcap_m = (mstr_price * MSTR_BASIC_SHARES) / 1e6

        # 官方 mNAV = Enterprise Value / BTC Reserve
        ev_m          = basic_mktcap_m + MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - MSTR_CASH_RESERVE_M
        official_mnav = ev_m / btc_reserve_m if btc_reserve_m > 0 else 0

        # CEBE mNAV = 股價 / 每股CEBE價值
        net_btc_value_m  = btc_reserve_m - MSTR_TOTAL_PREF_M - MSTR_TOTAL_DEBT_M
        cebe_per_share   = (net_btc_value_m * 1e6) / MSTR_ADSO if MSTR_ADSO > 0 else 0
        cebe_mnav        = mstr_price / cebe_per_share if cebe_per_share > 0 else 0
        cebe_sats        = int(cebe_per_share / btc_price * 1e8) if btc_price > 0 else 0
        drag_pct         = (MSTR_TOTAL_PREF_M + MSTR_TOTAL_DEBT_M) / btc_reserve_m * 100

        st.markdown("---")
        st.markdown("### 📈 即時 mNAV 儀表板")

        official_color = "#f3ba2f" if official_mnav >= 1 else "#0ecb81"
        cebe_color     = "#f3ba2f" if cebe_mnav >= 1 else "#0ecb81"

        st.markdown(f"""
            <div style="background:#181a20; border:1px solid #2b3139; border-radius:10px; padding:14px; margin-bottom:10px;">
                <div style="font-size:11px; color:#848e9c; margin-bottom:4px;">🏛️ 官方 mNAV（EV 口徑）</div>
                <div style="font-size:26px; font-weight:800; color:{official_color}; font-family:monospace;">{official_mnav:.3f}x</div>
                <div style="font-size:10px; color:#848e9c;">EV ${ev_m/1000:.2f}B ÷ BTC Reserve ${btc_reserve_m/1000:.2f}B</div>
            </div>
            <div style="background:#181a20; border:1px solid #2b3139; border-radius:10px; padding:14px; margin-bottom:10px;">
                <div style="font-size:11px; color:#848e9c; margin-bottom:4px;">🔬 CEBE mNAV（普通股真實溢價）</div>
                <div style="font-size:26px; font-weight:800; color:{cebe_color}; font-family:monospace;">{cebe_mnav:.3f}x</div>
                <div style="font-size:10px; color:#848e9c;">股價 ${mstr_price:.2f} ÷ CEBE ${cebe_per_share:.2f}（{cebe_sats:,} sats）</div>
                <div style="font-size:10px; color:#f6465d; margin-top:3px;">Drag（債務侵蝕率）= {drag_pct:.1f}%</div>
            </div>
        """, unsafe_allow_html=True)

        with st.expander("💡 什麼是 CEBE？"):
            st.markdown(f"""
**CEBE = Claim-Encumbered Bitcoin Equivalent**
**被債權人索償權壓著的比特幣等值**

買一股 MSTR，帳面上等於持有公司的 BTC，但債主（可轉債）和優先股股東有**優先索償權**。若公司清算，扣掉這些人的份額後，普通股股東才能拿到剩下的 BTC。

**當前清算順序：**
- BTC 持倉市值：${btc_reserve_m/1000:.2f}B
- 先扣 Debt + Pref：-${(MSTR_TOTAL_DEBT_M+MSTR_TOTAL_PREF_M)/1000:.2f}B
- 普通股淨BTC價值：${net_btc_value_m/1000:.2f}B
- ÷ 完全稀釋股數 {MSTR_ADSO/1e6:.1f}M 股
- **每股真實BTC淨值：${cebe_per_share:.2f}（{cebe_sats:,} sats）**

Drag = {drag_pct:.1f}%，代表你以為持有的 BTC，有 {drag_pct:.1f}% 屬於債主和優先股，不是你的。

CEBE mNAV > 1 = 仍在溢價，MSTR 發新股對普通股股東仍有利
CEBE mNAV < 1 = 折價，繼續發股會稀釋股東權益
""")

# ==========================================
# 3. 量化加權計分引擎
# ==========================================
funding_rate            = fetch_funding_rate()
daily_closes, df_weekly = fetch_historical_data()
fng_value               = fetch_fear_greed()

# 計算 BTC_PER_SHARE 用基本股數（官方 mNAV 口徑）
BTC_PER_SHARE = MSTR_BTC_HOLDINGS / MSTR_BASIC_SHARES

total_score, s1, s2, s3, s4, s5, s6, s7, s8, s9 = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
price_delta_str   = "0.00%"
ma200_w_current   = 0.0
mstr_premium_rate = 1.20

if ticker_data:
    price_delta_str = f"{ticker_data['delta']:+.2f}%"
    p_range = ticker_data['high'] - ticker_data['low']
    s1 = (((ticker_data['high'] - btc_price) / p_range) * 5.0) if p_range > 0 else 2.5
    bias = (btc_price - np.mean(daily_closes[-60:])) / np.mean(daily_closes[-60:]) if len(daily_closes) >= 60 else 0
    s2 = max(0.0, min(10.0, (0.0 - bias) / 0.20 * 10.0))
    r14 = (btc_price - daily_closes[-14]) / daily_closes[-14] if len(daily_closes) >= 14 else 0
    s3 = max(0.0, min(5.0,  (0.0 - r14) / 0.15 * 5.0))
    s4 = max(0.0, min(5.0,  (abs(ticker_data['delta']) / 5.0) * 5.0)) if ticker_data['delta'] < 0 else 0.0
    # s5：真正的恐懼貪婪指數（0=極度恐懼，100=極度貪婪），越恐懼分數越高
    s5 = max(0.0, min(15.0, ((40.0 - float(fng_value)) / 30.0) * 15.0))
    # s6：BTCUSDT 永續合約資金費率，費率越負分數越高
    s6 = max(0.0, min(15.0, ((0.0001 - funding_rate) / 0.0004) * 15.0))
    if mstr_price and btc_price > 0:
        estimated_nav     = btc_price * BTC_PER_SHARE
        mstr_premium_rate = mstr_price / estimated_nav if estimated_nav > 0 else 1.20
        s7 = max(0.0, min(15.0, ((2.5 - mstr_premium_rate) / 1.5) * 15.0))
    if not df_weekly.empty and len(df_weekly) >= 200:
        ma200_w_current = float(df_weekly.iloc[-1]['200WMA'])
        dist_200w = (btc_price - ma200_w_current) / ma200_w_current
        s8 = max(0.0, min(20.0, ((0.05 - dist_200w) / 0.10) * 20.0))
    last_halving       = datetime(2024, 4, 20, tzinfo=TAIPEI_TZ)
    days_since_halving = (datetime.now(TAIPEI_TZ) - last_halving).days
    cycle_progress     = (days_since_halving % 1460) / 1460
    s9 = max(0.0, min(5.0, (1.0 - cycle_progress) * 10.0)) if 500 <= days_since_halving % 1460 <= 800 else max(5.0, min(10.0, cycle_progress * 10.0))
    total_score = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8 + s9

# ==========================================
# 4. 分頁 A：直男量化經理人版
# ==========================================
if page == "直男量化經理人版":
    st.markdown("""
        <style>
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #0b0e11 !important;
            color: #eaecef !important;
            font-family: 'SF Pro Display', -apple-system, 'Segoe UI', Roboto, sans-serif;
        }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        footer { visibility: hidden; }
        .metric-card {
            background: linear-gradient(135deg, #181a20 0%, #1e222b 100%);
            border: 1px solid #2b3139; border-radius: 12px;
            padding: 16px 20px; margin-bottom: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            transition: transform 0.2s, border-color 0.2s;
        }
        .metric-card:hover { transform: translateY(-2px); border-color: #f3ba2f; }
        .metric-title { font-size: 14px; color: #848e9c; font-weight: 500; margin-bottom: 6px; display: flex; justify-content: space-between; }
        .metric-value { font-size: 16px; font-weight: 600; color: #eaecef; }
        .badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }
        .badge-gray   { background-color: #2b3139; color: #98a6b7; }
        .badge-yellow { background-color: rgba(243,186,47,0.15); color: #f3ba2f; }
        .badge-green  { background-color: rgba(14,203,129,0.15); color: #0ecb81; }
        .score-display { font-size: 48px; font-weight: 800; color: #f3ba2f; text-shadow: 0 0 20px rgba(243,186,47,0.3); font-family: 'Courier New', monospace; }
        </style>
    """, unsafe_allow_html=True)

    delta_color      = "#0ecb81" if ticker_data and ticker_data['delta'] >= 0 else "#f6465d"
    current_time_str = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')

    # 判斷恐懼貪婪標籤
    if fng_value <= 25:
        fng_label = "😱 極度恐懼"
        fng_color = "#0ecb81"
    elif fng_value <= 45:
        fng_label = "😟 恐懼"
        fng_color = "#f3ba2f"
    elif fng_value <= 55:
        fng_label = "😐 中性"
        fng_color = "#848e9c"
    elif fng_value <= 75:
        fng_label = "😏 貪婪"
        fng_color = "#f3ba2f"
    else:
        fng_label = "🤑 極度貪婪"
        fng_color = "#f6465d"

    st.markdown(f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #2b3139; margin-bottom:25px;">
            <div style="font-size:24px; font-weight:700; color:#eaecef; display:flex; align-items:center; gap:10px;">
                <span style="color:#f3ba2f;">🔮</span> BTC 9 因子抄底監控看板
            </div>
            <div style="font-size:12px; color:#848e9c; text-align:right;">
                系統狀態：<span style="color:#0ecb81; font-weight:bold;">● 即時串流中</span><br>
                更新時間：{current_time_str} (台北時間)
            </div>
        </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([1.1, 1])

    with col_left:
        st.markdown(f"""
            <div style="background:#181a20; padding:20px; border-radius:12px; border:1px solid #2b3139; margin-bottom:20px;">
                <div style="font-size:13px; color:#848e9c; font-weight:500; text-transform:uppercase; letter-spacing:1px;">BTC/USD 即時報價</div>
                <div style="display:flex; align-items:baseline; gap:15px; margin-top:5px;">
                    <span style="font-size:42px; font-weight:800; color:#eaecef; font-family:monospace;">${btc_price:,.2f}</span>
                    <span style="font-size:18px; font-weight:600; color:{delta_color};">{price_delta_str}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number", value=total_score, domain={'x': [0, 1], 'y': [0, 1]},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#848e9c", 'tickfont': {'size': 12}},
                'bar': {'color': "#ffffff", 'thickness': 0.25},
                'bgcolor': "rgba(0,0,0,0)", 'borderwidth': 1, 'bordercolor': "#2b3139",
                'steps': [
                    {'range': [0,   25], 'color': '#1e2026'},
                    {'range': [25,  55], 'color': '#1b2d2a'},
                    {'range': [55,  75], 'color': '#163d2c'},
                    {'range': [75, 100], 'color': '#3a1e22'},
                ],
            }
        ))
        fig_gauge.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font={'color': "#eaecef", 'family': "Arial"}, height=220,
            margin=dict(t=10, b=10, l=10, r=10)
        )
        st.plotly_chart(fig_gauge, use_container_width=True, config={'displayModeBar': False})

        if not df_weekly.empty:
            st.markdown(f"""
                <div style="font-size:14px; font-weight:600; color:#eaecef; margin:25px 0 10px 0;">
                    📈 長線跨週期趨勢矩陣（200WMA 支撐位：<span style="color:#f6465d; font-family:monospace;">${ma200_w_current:,.2f}</span>）
                </div>
            """, unsafe_allow_html=True)
            df_plot = df_weekly.dropna().copy()
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['Close'],  mode='lines', name='BTC 現貨',    line=dict(color='#f3ba2f', width=2)))
            fig_trend.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['200WMA'], mode='lines', name='200週均線', line=dict(color='#f6465d', width=1.5, dash='dash')))
            fig_trend.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, tickfont=dict(color="#848e9c"), title=""),
                yaxis=dict(showgrid=True, gridcolor='#2b3139', tickfont=dict(color="#848e9c"), type="log"),
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#848e9c", size=11))
            )
            st.plotly_chart(fig_trend, use_container_width=True, config={'displayModeBar': False})

    with col_right:
        st.markdown(f"""
            <div style="background:#181a20; padding:22px; border-radius:12px; border:1px solid #2b3139; margin-bottom:20px; text-align:center;">
                <div style="font-size:15px; color:#848e9c; font-weight:600; letter-spacing:1px;">🎯 經理人多因子總得分</div>
                <div class="score-display">{total_score:.1f} <span style="font-size:20px; color:#474d57;">/ 100 分</span></div>
            </div>
        """, unsafe_allow_html=True)

        def get_ui_badge(score, max_score):
            ratio = score / max_score if max_score > 0 else 0
            if ratio < 0.3:  return '<span class="badge badge-gray">🔴 正常震盪 / 暫無訊號</span>'
            if ratio < 0.65: return '<span class="badge badge-yellow">🟡 波動放大 / 蓄勢觀察</span>'
            return '<span class="badge" style="background:rgba(14,203,129,0.15);color:#0ecb81;">🟢 極度超跌 / 觸發左側抄底</span>'

        st.markdown(f"""
            <div class="metric-card">
                <div class="metric-title"><span>【重磅生死線】200週線大底防線 [s8] (權重: 20%)</span> {get_ui_badge(s8, 20.0)}</div>
                <div class="metric-value">{s8:.1f} / 20.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">歷史長線終極防禦支撐位</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【美股風向球】MSTR mNAV 現貨溢價 [s7] (權重: 15%)</span> {get_ui_badge(s7, 15.0)}</div>
                <div class="metric-value">{s7:.1f} / 15.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">簡化溢價: {mstr_premium_rate:.2f}x｜{BTC_PER_SHARE*1e8:,.0f} Sats/股</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【衍生品關卡】BTCUSDT永續合約資金費率 [s6] (權重: 15%)</span> {get_ui_badge(s6, 15.0)}</div>
                <div class="metric-value">{s6:.1f} / 15.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">Binance USDT-M 即時費率: {funding_rate*100:+.4f}%</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【韭菜探針】加密市場恐懼貪婪指數 [s5] (權重: 15%)</span> {get_ui_badge(s5, 15.0)}</div>
                <div class="metric-value">{s5:.1f} / 15.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">Alternative.me F&G: {fng_value} / 100 &nbsp; {fng_label}</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【成本拉力】大盤生命線偏離度 [s2] (權重: 10%)</span> {get_ui_badge(s2, 10.0)}</div>
                <div class="metric-value">{s2:.1f} / 10.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">現價離 MA60 負乖離比例</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【時空定位】四年減半週期進度 [s9] (權重: 10%)</span> {get_ui_badge(s9, 10.0)}</div>
                <div class="metric-value">{s9:.1f} / 10.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">歷史牛熊週期時間節點定位</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【短期套牢】兩週散戶虧損洗盤 [s3] (權重: 5%)</span> {get_ui_badge(s3, 5.0)}</div>
                <div class="metric-value">{s3:.1f} / 5.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">14天內追高籌碼清洗折價度</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【恐懼割肉】今日盤中下殺強度 [s4] (權重: 5%)</span> {get_ui_badge(s4, 5.0)}</div>
                <div class="metric-value">{s4:.1f} / 5.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">24小時日內閃崩幅度</span></div>
            </div>
            <div class="metric-card">
                <div class="metric-title"><span>【日內微調】今日撿便宜便宜度 [s1] (權重: 5%)</span> {get_ui_badge(s1, 5.0)}</div>
                <div class="metric-value">{s1:.1f} / 5.0 分 <span style="font-size:12px;color:#848e9c;font-weight:normal;margin-left:10px;">市價與今日插針最低點鄰近度</span></div>
            </div>
        """, unsafe_allow_html=True)

    # ── CEBE 壓力測試模擬表 ────────────────────────────────
    st.markdown("---")
    st.subheader("📊 MSTR CEBE 股價真實價值壓力測試模擬")
    st.markdown(f"基於 **{MSTR_BTC_HOLDINGS:,} BTC** 持倉，扣除所有債務與優先股索償後，模擬不同 BTC 幣價情境下每股真實 BTC 淨值（CEBE 股價）區間：")

    sim_btc_prices = [70000, 100000, 150000]
    sim_scenarios  = ["熊市低迷情境", "目前市場基準", "狂暴狂牛情境"]
    rows = []
    for p, name in zip(sim_btc_prices, sim_scenarios):
        sim_btc_reserve_m  = (MSTR_BTC_HOLDINGS * p) / 1e6
        sim_net_value_m    = sim_btc_reserve_m - MSTR_TOTAL_PREF_M - MSTR_TOTAL_DEBT_M
        sim_cebe_per_share = (sim_net_value_m * 1e6) / MSTR_ADSO if MSTR_ADSO > 0 else 0
        sim_drag           = (MSTR_TOTAL_PREF_M + MSTR_TOTAL_DEBT_M) / sim_btc_reserve_m * 100
        rows.append({
            "情境":                     name,
            "BTC 模擬價格":             f"${p:,.0f}",
            "每股 CEBE（真實BTC淨值）":  f"${sim_cebe_per_share:,.2f}",
            "Drag（債務侵蝕率）":        f"{sim_drag:.1f}%",
            "1.2x 合理防線":            f"${sim_cebe_per_share * 1.2:,.2f}",
            "1.8x 牛市泡沫線":          f"${sim_cebe_per_share * 1.8:,.2f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("""
        <div style="background:#181a20; border:1px solid #2b3139; border-radius:8px; padding:20px; margin:15px 0;">
            <p style="color:#ffffff; font-size:15px; font-weight:bold; margin-bottom:12px;">💡 如何解讀 CEBE 股價壓力測試？</p>
            <ul style="color:#ffffff; font-size:14px; line-height:1.7; padding-left:20px;">
                <li style="margin-bottom:8px;"><b>每股 CEBE</b>：扣除可轉債和優先股的優先索償後，普通股真正對應的 BTC 淨值。這才是你實際持有的資產。</li>
                <li style="margin-bottom:8px;"><b>Drag（拖累率）</b>：BTC 持倉中被債務與優先股吃掉的比例。BTC 漲越多，Drag 越小，普通股分到越多。</li>
                <li style="margin-bottom:8px;"><b>1.2x 防線</b>：市場回歸理性時的估值下限，股價跌到此區間為左側抄底參考點。</li>
                <li><b>1.8x 泡沫線</b>：市場狂熱時的估值上限，超過此線需謹慎追多。</li>
            </ul>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("🔬 全套 9 因子量化核心指標定義與數據來源說明書"):
        st.markdown(f"""
        ### 📊 核心加權計分邏輯說明
        本模型共由 9 個量化因子組成，總分為 100 分。**總得分 > 55 分**時，系統判定進入極度超跌區，左側抄底勝率顯著提升。

        ---
        #### **1. 【重磅生死線】200週線大底防線 [s8]** — 權重 20%
        計算現價與 200WMA 偏離比例。數據來源：`yfinance` 週線歷史資料庫。

        #### **2. 【美股風向球】MSTR mNAV 現貨溢價 [s7]** — 權重 15%
        監控 MSTR 股價相對 BTC 市值的簡化溢價倍數。數據來源：`yfinance` MSTR 即時報價。

        #### **3. 【衍生品關卡】BTCUSDT永續合約資金費率 [s6]** — 權重 15%
        ⚡ **已修正**：改用 Binance USDT-M Futures REST API（`fapi.binance.com`），抓取 BTCUSDT 永續合約資金費率。
        費率轉負 = 市場多頭清算完畢，為左側抄底訊號。當前費率：**{funding_rate*100:+.4f}%**

        #### **4. 【韭菜探針】加密市場恐懼貪婪指數 [s5]** — 權重 15%
        ⚡ **已修正**：改用 Alternative.me 免費公開 API（`api.alternative.me/fng`），這是真正的加密市場恐懼貪婪指數，
        由 BTC 波動率、市場動量、社群媒體、Google Trends、BTC 市佔率等 5 大因子合成。0=極度恐懼，100=極度貪婪。
        當前讀數：**{fng_value} / 100（{fng_label}）**

        #### **5. 【成本拉力】大盤生命線偏離度 [s2]** — 權重 10%
        現價低於 MA60 超過 20% 時，成本拉力回歸動能極強。數據來源：`yfinance` 日線滾動計算。

        #### **6. 【時空定位】四年減半週期進度 [s9]** — 權重 10%
        自動計算距 2024/4/20 減半日的週期進度，500~800天為歷史築底區間。

        #### **7. 【短期套牢】兩週散戶虧損洗盤 [s3]** — 權重 5%
        量化近兩週追高籌碼被套深度。數據來源：`yfinance` 日線回溯。

        #### **8. 【恐懼割肉】今日盤中下殺強度 [s4]** — 權重 5%
        捕捉單日多殺多閃崩幅度，插針撿便宜訊號。

        #### **9. 【日內微調】今日撿便宜便宜度 [s1]** — 權重 5%
        現價在今日高低震盪區間中的位置，越靠近最低點分數越高。
        """)

# ==========================================
# 5. 分頁 B：文元萌化版
# ==========================================
else:
    st.markdown("""
        <style>
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #fff5f5 !important; color: #4a4a4a !important;
            font-family: 'PingFang TC', system-ui, sans-serif;
        }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        footer { visibility: hidden; }
        .cute-card { background:#ffffff; border:3px solid #ffb6c1; border-radius:20px; padding:20px; margin-bottom:15px; box-shadow:0 8px 16px rgba(255,182,193,0.2); transition:all 0.3s ease; }
        .cute-card:hover { transform:scale(1.01); box-shadow:0 10px 20px rgba(255,182,193,0.4); }
        .cute-title { font-size:16px; color:#ff69b4; font-weight:bold; display:flex; justify-content:space-between; align-items:center; }
        .cute-value { font-size:14px; color:#555555; margin-top:8px; line-height:1.5; }
        .cute-badge { padding:4px 12px; border-radius:20px; font-size:12px; font-weight:bold; }
        .badge-sleep { background-color:#f3f3f3; color:#9b9b9b; border:1px solid #ddd; }
        .badge-watch { background-color:#ffeaa7; color:#d63031; border:1px solid #f1c40f; }
        .badge-buy   { background-color:#ff7675; color:#ffffff; }
        .heart-score-display { font-size:56px; font-weight:bold; color:#ff69b4; font-family:system-ui,sans-serif; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("""
        <div style="text-align:center; padding:10px 0; border-bottom:3px dashed #ffb6c1; margin-bottom:25px;">
            <div style="font-size:26px; font-weight:bold; color:#ff69b4;">💖 文元專屬：比特幣「能不能買包包」終極防割监控儀表板</div>
            <div style="font-size:14px; color:#7f8c8d; margin-top:8px;">👩‍🏫 <b>魏文元專屬小叮嚀：</b>老公有沒有亂買看這裡就對了！</div>
        </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([1, 1])

    with col_left:
        delta_emoji = "📈 太棒了寶貝！" if ticker_data and ticker_data['delta'] >= 0 else "📉 跌倒了拍拍："
        delta_color = "#2ecc71" if ticker_data and ticker_data['delta'] >= 0 else "#e74c3c"
        st.markdown(f"""
            <div style="background:white; padding:25px; border-radius:20px; border:3px solid #ffb6c1; text-align:center;">
                <div style="font-size:16px; color:#7f8c8d; font-weight:bold;">🪙 比特幣現在的價格 (BTC/USD)</div>
                <div style="font-size:46px; font-weight:bold; color:#ff69b4; margin:10px 0; font-family:monospace;">${btc_price:,.2f}</div>
                <div style="font-size:16px; font-weight:bold; color:{delta_color};">{delta_emoji} {price_delta_str}</div>
            </div>
        """, unsafe_allow_html=True)

        if total_score < 30:
            advice_title = "❌ 先去睡覺，千萬不要動！"
            advice_desc  = "現在市場大家都瘋了在亂買，進去就是當韭菜送人頭。現在敢亂買的話，直接罰老公去跪算盤！"
        elif total_score < 60:
            advice_title = "👀 搬小板凳，坐著看戲就好"
            advice_desc  = "市場現在有點小震盪、不上不下的。我們繼續優雅地喝貴婦下午茶，等真正大特價再說。"
        else:
            advice_title = "🛍️ 限時大特價！百貨週年慶衝啊！"
            advice_desc  = "傳說中的全宇宙打折季來了！大家都嚇到把寶貝亂扔，現在正是叫老公去撿便宜、幫我們賺包包基金的黃金時刻！"

        st.markdown(f"""
            <br>
            <div style="background:linear-gradient(135deg,#fff0f5 0%,#ffe4e1 100%); padding:30px; border-radius:25px; border:3px solid #ff69b4; text-align:center;">
                <div style="font-size:18px; color:#db7093; font-weight:bold;">🛍️ 當前能不能撿便宜指數</div>
                <div class="heart-score-display">❤️ {total_score:.1f} <span style="font-size:22px; color:#db7093;">/ 100 滿分</span></div>
                <div style="margin-top:15px; padding:15px; background:white; border-radius:15px; border:2px solid #ffb6c1;">
                    <div style="font-size:18px; font-weight:bold; color:#e74c3c;">{advice_title}</div>
                    <div style="font-size:14px; color:#555555; margin-top:8px; line-height:1.6;">{advice_desc}</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col_right:
        def get_cute_badge(score, max_score):
            ratio = score / max_score if max_score > 0 else 0
            if ratio >= 0.65: return '<span class="cute-badge badge-buy">🔥 百貨週年慶衝啊！</span>'
            if ratio >= 0.3:  return '<span class="cute-badge badge-watch">🧐 有點風吹草動</span>'
            return '<span class="cute-badge badge-sleep">💤 大家都還在睡</span>'

        # 恐懼貪婪文元版說明
        if fng_value <= 25:
            fng_cute = f"市場現在超級害怕！（{fng_value}/100）大家都在逃跑，反而是好時機！"
        elif fng_value <= 45:
            fng_cute = f"大家有點擔心（{fng_value}/100），保持觀望就好。"
        elif fng_value <= 55:
            fng_cute = f"市場情緒中性（{fng_value}/100），不上不下。"
        elif fng_value <= 75:
            fng_cute = f"大家開始貪婪了（{fng_value}/100），小心追高！"
        else:
            fng_cute = f"市場極度瘋狂（{fng_value}/100），老公千萬不能追！"

        st.markdown(f"""
            <div class="cute-card">
                <div class="cute-title"><span>🩸 歷史級終極防禦大鐵底 [s8]</span> {get_cute_badge(s8, 20.0)}</div>
                <div class="cute-value"><b>特價得分：{s8:.1f} / 20.0 滿分</b><br>
                <span style="color:#7f8c8d;font-size:13px;">💡 跌到這裡就是幾年才一次的地下室清倉價！</span></div>
            </div>
            <div class="cute-card">
                <div class="cute-title"><span>🤡 美股大韭菜有沒有吹泡泡 [s7]</span> {get_cute_badge(s7, 15.0)}</div>
                <div class="cute-value"><b>特價得分：{s7:.1f} / 15.0 滿分</b><br>
                <span style="color:#7f8c8d;font-size:13px;">💡 溢價倍數：{mstr_premium_rate:.2f}x，數字越低泡沫越小！</span></div>
            </div>
            <div class="cute-card">
                <div class="cute-title"><span>💸 衍生品空頭有沒有投降 [s6]</span> {get_cute_badge(s6, 15.0)}</div>
                <div class="cute-value"><b>特價得分：{s6:.1f} / 15.0 滿分</b><br>
                <span style="color:#7f8c8d;font-size:13px;">💡 USDT永續費率：{funding_rate*100:+.4f}%，負數代表多頭被清洗完了！</span></div>
            </div>
            <div class="cute-card">
                <div class="cute-title"><span>😱 市場現在有多恐慌 [s5]</span> {get_cute_badge(s5, 15.0)}</div>
                <div class="cute-value"><b>特價得分：{s5:.1f} / 15.0 滿分</b><br>
                <span style="color:#7f8c8d;font-size:13px;">💡 {fng_cute}</span></div>
            </div>
        """, unsafe_allow_html=True)
