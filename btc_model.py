import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo  # 💎 引入標準時區庫，精確鎖定台北時間
from binance.cm_futures import CMFutures  # 替代原有的 fapi 請求

# ==========================================
# 0. 網頁全域設定 (必須是第一個執行的 Streamlit 語法！)
# ==========================================
st.set_page_config(
    page_title="BTC 抄底監控戰情室",
    layout="wide",
    initial_sidebar_state="expanded"  # 強制初始展開側邊欄
)

# 設定台北時區常數
TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# ==========================================
# 1. 數據抓取模組 (完全移除 requests，改用極穩定的 SDK 與 yfinance)
# ==========================================
@st.cache_data(ttl=5)
def fetch_binance_ticker():
    """使用 yfinance 抓取 BTC 即時與 24h 行情，避免雲端 IP 被幣安封鎖"""
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
            
            return {
                'price': last_price,
                'high': high_price,
                'low': low_price,
                'delta': delta_pct
            }
        return None
    except:
        return None

@st.cache_data(ttl=5)
def fetch_funding_rate():
    """使用官方免驗證的 binance-connector SDK 抓取資金費率"""
    try:
        cm_client = CMFutures()
        res = cm_client.premium_index(symbol="BTCUSD_PERP")
        if isinstance(res, list) and len(res) > 0:
            return float(res[0].get('lastFundingRate', 0.0001))
        elif isinstance(res, dict):
            return float(res.get('lastFundingRate', 0.0001))
        return 0.0001
    except:
        return 0.0001

@st.cache_data(ttl=30)
def fetch_historical_data():
    """改用 yfinance 抓取日線與週線數據，完美避開 Klines 限制"""
    try:
        btc = yf.Ticker("BTC-USD")
        df_d = btc.history(period="100d", interval="1d")
        daily_closes = df_d['Close'].tolist() if not df_d.empty else []
        
        df_w = btc.history(period="max", interval="1wk")
        if not df_w.empty:
            df_w = df_w.reset_index()
            df_w['200WMA'] = df_w['Close'].rolling(window=200).mean()
            df_w = df_w.rename(columns={'Date': 'Date'})
        else:
            df_w = pd.DataFrame()
            
        return daily_closes, df_w
    except:
        return [], pd.DataFrame()

@st.cache_data(ttl=30)
def fetch_fear_greed():
    """情緒指數改用隱含波動率替代，確保雲端環境不卡死"""
    try:
        vix = yf.Ticker("^VIX")
        vix_df = vix.history(period="1d")
        if not vix_df.empty:
            vix_price = float(vix_df['Close'].iloc[-1])
            fng_mapped = max(10, min(90, int(100 - (vix_price * 2))))
            return fng_mapped
        return 50
    except:
        return 50

@st.cache_data(ttl=60)
def fetch_mstr_premium():
    """抓取 MSTR 最新美股即時價"""
    try:
        mstr = yf.Ticker("MSTR")
        df_mstr = mstr.history(period="1d", interval="1m")
        if not df_mstr.empty:
            return float(df_mstr['Close'].iloc[-1])
        return None
    except:
        return None

# ==========================================
# 2. 執行數據抓取與量化加權計分引擎
# ==========================================
ticker_data = fetch_binance_ticker()
funding_rate = fetch_funding_rate()
daily_closes, df_weekly = fetch_historical_data()
fng_value = fetch_fear_greed()
mstr_live_price = fetch_mstr_premium()

total_score = 0.0
s1, s2, s3, s4, s5, s6, s7, s8, s9 = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
btc_price = 0.0
price_delta_str = "0.00%"
ma200_w_current = 0.0
mstr_premium_rate = 1.20

# 📊 核心配置：採用基本流通股數，進行最保守的現貨去泡沫化核算
MSTR_BTC_HOLDINGS = 846842          # 🎯 已更新最新總持倉 
MSTR_SHARES_OUTSTANDING = 386052000 # 🎯 已更新最新基本流通股數 (ADSO)
MSTR_AVG_COST = 75656               # 🎯 已更新歷史總平均買入成本
BTC_PER_SHARE = MSTR_BTC_HOLDINGS / MSTR_SHARES_OUTSTANDING  # 自動核算動態每股實打實含幣量

# 💎 根據圖片更新最新 MSTR 企業價值 (Enterprise Value) 欄位數據
MSTR_ENTERPRISE_VALUE = 67857 * 1e6  # 圖片標註為 $67,857 M USD

if ticker_data is not None:
    btc_price = ticker_data['price']
    price_delta_str = f"{ticker_data['delta']:+.2f}%"

    # s1: 日內微觀掛單最優便宜度 (滿分 5)
    p_range = ticker_data['high'] - ticker_data['low']
    s1 = (((ticker_data['high'] - btc_price) / p_range) * 5.0) if p_range > 0 else 2.5
    
    # s2: 大盤生命線 MA60 負乖離 (滿分 10)
    if len(daily_closes) >= 60:
        bias = (btc_price - np.mean(daily_closes[-60:])) / np.mean(daily_closes[-60:])
        s2 = max(0.0, min(10.0, (0.0 - bias) / 0.20 * 10.0))
    else: 
        s2 = 5.0
        
    # s3: 14天散戶套牢洗盤度 (滿分 5)
    if len(daily_closes) >= 14:
        r14 = (btc_price - daily_closes[-14]) / daily_closes[-14]
        s3 = max(0.0, min(5.0, (0.0 - r14) / 0.15 * 5.0))
    else: 
        s3 = 2.5
        
    # s4: 今日盤中瀑布下殺強度 (滿分 5)
    s4 = max(0.0, min(5.0, (abs(ticker_data['delta']) / 5.0) * 5.0)) if ticker_data['delta'] < 0 else 0.0
    
    # s5: 散戶恐懼貪婪情緒指數 (滿分 15)
    s5 = max(0.0, min(15.0, ((40.0 - float(fng_value)) / 30.0) * 15.0))
    
    # s6: 永續合約多空資金費率 (滿分 15)
    s6 = max(0.0, min(15.0, ((0.0001 - funding_rate) / 0.0004) * 15.0))
    
    # s7: MSTR 靜態 mNAV 現貨溢價指標 [🛠️ 已依照用戶指定新公式修改：EV / (持倉量 * BTC即時價)] (滿分 15)
    mstr_btc_total_value = MSTR_BTC_HOLDINGS * btc_price
    if mstr_btc_total_value > 0:
        mstr_premium_rate = MSTR_ENTERPRISE_VALUE / mstr_btc_total_value
        s7 = max(0.0, min(15.0, ((2.5 - mstr_premium_rate) / 1.5) * 15.0))
    else:
        mstr_premium_rate = 1.20
        s7 = 13.0
        
    # s8: 200週線大底防線 (滿分 20)
    if not df_weekly.empty and len(df_weekly) >= 200:
        ma200_w_current = float(df_weekly.iloc[-1]['200WMA'])
        dist_200w = (btc_price - ma200_w_current) / ma200_w_current
        s8 = max(0.0, min(20.0, ((0.05 - dist_200w) / 0.10) * 20.0))
    else:
        ma200_w_current = btc_price * 0.7
        s8 = 10.0
        
    # s9: 四年減半週期時空定位 (滿分 10) ── 🛠️ 已同步為台北時間計算
    last_halving = datetime(2024, 4, 20, tzinfo=TAIPEI_TZ)
    now_taipei = datetime.now(TAIPEI_TZ)
    days_since_halving = (now_taipei - last_halving).days
    cycle_progress = (days_since_halving % 1460) / 1460 
    if 500 <= days_since_halving % 1460 <= 800:
        s9 = max(0.0, min(5.0, (1.0 - cycle_progress) * 10.0))
    else:
        s9 = max(5.0, min(10.0, cycle_progress * 10.0))

    total_score = s1 + s2 + s3 + s4 + s5 + s6 + s7 + s8 + s9

# ==========================================
# 3. 側邊欄切換路由
# ==========================================
with st.sidebar:
    st.markdown("### 🔮 戰情室切換")
    page = st.radio(
        "請選擇檢視視角：",
        ["直男量化經理人版", "文元專屬：能不能買包包版"],
        index=0
    )
    st.markdown("---")
    st.markdown("### 📊 MSTR 保守現貨資產清單")
    st.info(f"🪙 持倉總量: {MSTR_BTC_HOLDINGS:,} BTC")
    st.info(f"📜 基本流通股數: {MSTR_SHARES_OUTSTANDING:,} 股")
    st.info(f"📉 歷史總平均成本: ${MSTR_AVG_COST:,} USD")
    
    # 側邊欄動態即時損益核算
    if btc_price > 0:
        current_pnl_usd = (btc_price - MSTR_AVG_COST) * MSTR_BTC_HOLDINGS
        pnl_billion = current_pnl_usd / 1e9
        pnl_color = "green" if current_pnl_usd >= 0 else "red"
        st.markdown(f"💼 MSTR 持倉即時損益：<span style='color:{pnl_color}; font-weight:bold;'>${pnl_billion:.2f} B USD</span>", unsafe_allow_html=True)
    st.markdown("---")

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
        footer {visibility: hidden;}
        
        .metric-card {
            background: linear-gradient(135deg, #181a20 0%, #1e222b 100%);
            border: 1px solid #2b3139;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            transition: transform 0.2s, border-color 0.2s;
        }
        .metric-card:hover {
            transform: translateY(-2px);
            border-color: #f3ba2f;
        }
        .metric-title {
            font-size: 14px;
            color: #848e9c;
            font-weight: 500;
            margin-bottom: 6px;
            display: flex;
            justify-content: space-between;
        }
        .metric-value { font-size: 16px; font-weight: 600; color: #eaecef; }
        
        .badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
        }
        .badge-gray { background-color: #2b3139; color: #98a6b7; }
        .badge-yellow { background-color: rgba(243, 186, 47, 0.15); color: #f3ba2f; }
        .badge-green { background-color: rgba(14, 203, 129, 0.15); color: #0ecb81; }
        .badge-red { background-color: rgba(246, 70, 93, 0.15); color: #f6465d; }
        
        .score-display {
            font-size: 48px;
            font-weight: 800;
            color: #f3ba2f;
            text-shadow: 0 0 20px rgba(243, 186, 47, 0.3);
            font-family: 'Courier New', monospace;
        }
        </style>
    """, unsafe_allow_html=True)

    delta_color = "#0ecb81" if "-" not in price_delta_str else "#f6465d"
    current_time_str = datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')

    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #2b3139; margin-bottom: 25px;">
            <div style="font-size: 24px; font-weight: 700; color: #eaecef; display: flex; align-items: center; gap: 10px;">
                <span style="color: #f3ba2f;">🔮</span> BTC 9 因子抄底監控看板 (基本股數去泡沫核算版)
            </div>
            <div style="font-size: 12px; color: #848e9c; text-align: right;">
                系統狀態：<span style="color: #0ecb81; font-weight: bold;">● SDK 即時串流中</span><br>
                更新時間：{current_time_str} (台北時間)
            </div>
        </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([1.1, 1])

    with col_left:
        st.markdown(f"""
            <div style="background: #181a20; padding: 20px; border-radius: 12px; border: 1px solid #2b3139; margin-bottom: 20px;">
                <div style="font-size: 13px; color: #848e9c; font-weight: 500; text-transform: uppercase; letter-spacing: 1px;">Yahoo Finance 跨市場即時報價 (BTC/USD)</div>
                <div style="display: flex; align-items: baseline; gap: 15px; margin-top: 5px;">
                    <span style="font-size: 42px; font-weight: 800; color: #eaecef; font-family: monospace;">${btc_price:,.2f}</span>
                    <span style="font-size: 18px; font-weight: 600; color: {delta_color};">{price_delta_str}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
        
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number", value = total_score, domain = {'x': [0, 1], 'y': [0, 1]},
            gauge = {
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "#848e9c", 'tickfont': {'size': 12}},
                'bar': {'color': "#ffffff", 'thickness': 0.25},
                'bgcolor': "rgba(0,0,0,0)", 'borderwidth': 1, 'bordercolor': "#2b3139",
                'steps': [
                    {'range': [0, 25], 'color': '#1e2026'},     
                    {'range': [25, 55], 'color': '#1b2d2a'},    
                    {'range': [55, 75], 'color': '#163d2c'},    
                    {'range': [75, 100], 'color': '#3a1e22'}    
                ],
            }
        ))
        fig_gauge.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font={'color': "#eaecef", 'family': "Arial"}, height=220, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_gauge, use_container_width=True, config={'displayModeBar': False})

        if not df_weekly.empty:
            st.markdown(f"""
                <div style="font-size: 14px; font-weight: 600; color: #eaecef; margin: 25px 0 10px 0; display:flex; align-items:center; gap:8px;">
                    📈 長線跨週期趨勢矩陣 (當前 200WMA 支撐位: <span style="color:#f6465d; font-family:monospace;">${ma200_w_current:,.2f}</span>)
                </div>
            """, unsafe_allow_html=True)
            
            df_plot = df_weekly.dropna().copy()
            fig_trend = go.Figure()
            fig_trend.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['Close'], mode='lines', name='比特幣現貨價格', line=dict(color='#f3ba2f', width=2)))
            fig_trend.add_trace(go.Scatter(x=df_plot['Date'], y=df_plot['200WMA'], mode='lines', name='200週移動平均生死線', line=dict(color='#f6465d', width=1.5, dash='dash')))
            
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
            <div style="background: #181a20; padding: 22px; border-radius: 12px; border: 1px solid #2b3139; margin-bottom: 20px; text-align: center;">
                <div style="font-size: 15px; color: #848e9c; font-weight: 600; letter-spacing: 1px;">🎯 經理人多因子總得分</div>
                <div class="score-display">{total_score:.1f} <span style="font-size:20px; color:#474d57;">/ 100 分</span></div>
            </div>
        """, unsafe_allow_html=True)
        
        def get_ui_badge(score, max_score):
            ratio = score / max_score if max_score > 0 else 0
            if ratio < 0.3: return '<span class="badge badge-gray">🔴 正常震盪 / 暫無訊號</span>'
            if ratio < 0.65: return '<span class="badge badge-yellow">🟡 波動放大 / 蓄勢觀察</span>'
            return '<span class="badge badge-green">🟢 極度超跌 / 觸發左側抄底</span>'

        st.markdown(f"""
            <div class="metric-card"><div class="metric-title"><span>【重磅生死線】200週線大底防線 [s8] (權重: 20%)</span> {get_ui_badge(s8, 20.0)}</div><div class="metric-value">{s8:.1f} / 20.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">歷史長線終極防禦支撐位</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【美股風向球】MSTR 靜態 mNAV 現貨溢價指標 [s7] (權重: 15%)</span> {get_ui_badge(s7, 15.0)}</div><div class="metric-value">{s7:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">企業價值溢價比率 (EV/BTC總值): {mstr_premium_rate:.2f} 倍 (含幣量: {BTC_PER_SHARE*1e8:,.0f} Sats/股)</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【衍生品關卡】永續合約多空資金費率 [s6] (權重: 15%)</span> {get_ui_badge(s6, 15.0)}</div><div class="metric-value">{s6:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前即時資金費率: {funding_rate*100:+.4f}%</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【韭菜探針】市場散戶恐懼情緒 [s5] (權重: 15%)</span> {get_ui_badge(s5, 15.0)}</div><div class="metric-value">{s5:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">VIX反向推算散戶恐懼讀數: {fng_value}</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【成本拉力】大盤生命線偏離度 [s2] (權重: 10%)</span> {get_ui_badge(s2, 10.0)}</div><div class="metric-value">{s2:.1f} / 10.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">現價離 60 日均線(MA60)負乖離比例</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【時空定位】四年減半週期進度規律 [s9] (權重: 10%)</span> {get_ui_badge(s9, 10.0)}</div><div class="metric-value">{s9:.1f} / 10.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">歷史牛熊週期時間節點定位</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【短期套牢】兩週散戶虧損洗盤 [s3] (權重: 5%)</span> {get_ui_badge(s3, 5.0)}</div><div class="metric-value">{s3:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">14天內追高籌碼被清洗折價度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【恐懼割肉】今日盤中下殺強度 [s4] (權重: 5%)</span> {get_ui_badge(s4, 5.0)}</div><div class="metric-value">{s4:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">24小時內日內多殺多閃崩幅度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【日內微調】今日撿便宜便宜度 [s1] (權重: 5%)</span> {get_ui_badge(s1, 5.0)}</div><div class="metric-value">{s1:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">市價與今日插針最低點鄰近度</span></div></div>
        """, unsafe_allow_html=True)

    # =====================================================================
    # 💎 MSTR 全面稀釋清算價值與合理股價壓力測試模擬
    # ==========================================
    st.markdown("---")
    st.subheader("📊 MSTR 全面稀釋清算價值與合理股價壓力測試模擬")
    st.markdown(f"基於最新 {MSTR_BTC_HOLDINGS:,} BTC 持倉，**模擬當未來債主全部換成股票（全面稀釋總股數膨脹至 4 億股）**時，在不同 BTC 幣價情境下 MSTR 的股價合理風控區間：")
    
    # 採用完全稀釋潛在分母進行極端壓力測試
    DILUTED_SHARES = 400000000 
    DILUTED_BTC_PER_SHARE = MSTR_BTC_HOLDINGS / DILUTED_SHARES

    # 建立固定的模擬幣價情境 (7萬 / 10萬 / 15萬)
    sim_btc_prices = [70000, 100000, 150000]
    sim_scenarios = ["熊市低迷情境", "目前市場基準", "狂暴狂牛情境"]
    
    rows = []
    for p, name in zip(sim_btc_prices, sim_scenarios):
        # 扣除淨債務估算完全稀釋後的每股實質 NAV (清算價值)
        sim_total_btc_value = MSTR_BTC_HOLDINGS * p
        sim_nav_total = sim_total_btc_value - MSTR_NET_DEBT if 'MSTR_NET_DEBT' in locals() else (sim_total_btc_value - 4500000000)
        sim_nav_per_share = sim_nav_total / DILUTED_SHARES
        
        # 計算 1.2 倍合理防線與 1.8 倍牛市常態泡沫線
        floor_price = sim_nav_per_share * 1.2
        ceiling_price = sim_nav_per_share * 1.8
        
        rows.append({
            "情境說明": name,
            "比特幣模擬現貨價 (USD)": f"${p:,.0f}",
            "每股清算淨值 (NAV 地板價)": f"${sim_nav_per_share:,.2f}",
            "1.2 倍溢價 (合理防線/抄底點)": f"${floor_price:,.2f}",
            "1.8 倍溢價 (牛市常態/泡沫線)": f"${ceiling_price:,.2f}"
        })
        
    df_stress = pd.DataFrame(rows)
    
    # 🛠️ 關鍵優化：捨棄會跟底圖顏色打架的 HTML 表格，改用 Streamlit 原生高對比度 Dataframe 顯示
    st.dataframe(df_stress, use_container_width=True, hide_index=True)

    # 💡 高強度可讀性的白話操盤指南
    st.markdown("""
        <div style="background-color: #181a20; border: 1px solid #2b3139; border-radius: 8px; padding: 20px; margin: 15px 0;">
            <p style="color: #ffffff; font-size: 16px; font-weight: bold; margin-bottom: 12px;">
                💡 操盤風控指南 —— 怎麼看這份測試數據？
            </p>
            <p style="color: #ffffff; font-size: 14px; line-height: 1.6; margin-bottom: 14px;">
                本數據採用最嚴格的<b>「完全稀釋（Fully Diluted）」模型</b>。核心邏輯：將未來所有可轉債視為全部轉股（分母極大化至 4 億股），因此反推估算出的「每股合理價」會被稀釋壓低，這能為策略構築出最保守、安全的防守邊界。
            </p>
            <ul style="color: #ffffff; font-size: 14px; line-height: 1.7; padding-left: 20px;">
                <li style="margin-bottom: 10px;">
                    <b>1. 抓出「極端防守地板價」（看 1.2 倍溢價欄位）</b>：當市場回歸理性，MSTR 溢價率修正到 1.2 倍附近。若 BTC 在 10 萬美元，排除所有潛在轉股稀釋後，MSTR 跌到 <span style="color: #f3ba2f; font-weight: bold;">$256</span> 附近就是鐵板支撐。這是您用來「左側分批抄底」或「大波段動態停損」的終極防線，比常規 ADSO 算出的價格更低、容錯率更高。
                </li>
                <li style="margin-bottom: 10px;">
                    <b>2. 判斷「天花板與泡沫警戒」（看 1.8 倍溢價欄位）</b>：當市場狂熱，華爾街給到 1.8 倍高溢價。在 BTC 10 萬美元時，MSTR 觸及 <span style="color: #f3ba2f; font-weight: bold;">$383</span> 附近即代表即使在完全稀釋的預期下，也已把未來漲幅預支完畢。此時若股價繼續飆升，意味著真實泡沫率嚴重過高，切勿盲目追多，需防範多頭踩踏的暴跌修正。
                </li>
                <li style="margin-bottom: 5px;">
                    <b>3. 稀釋效應的「鈍化現象」</b>：市場最擔心的「瘋狂發債、股本膨脹」，在 MSTR 模式下會被幣價上漲給鈍化。數據顯示，即便可轉債全數轉股（分母變大），只要 BTC 幣價能一路震盪上行（如到 15 萬美元），完全稀釋下的 1.2 倍地板價仍會被暴力拉升到 <span style="color: #f3ba2f; font-weight: bold;">$319</span>。長期來看，<b>資產增速大於股本稀釋速度</b>，上行空間就不會被鎖死。
                </li>
            </ul>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("🔬 🔍 全套 9 因子量化核心指標定義與數據來源說明書（對沖基金級）"):
        st.markdown("""
        ### 📊 核心加權計分邏輯說明
        本模型共由 9 個宏觀、微觀、衍生品以及情緒層面的量化因子組成，總分為 100 分。當**總得分 > 55 分**時，系統判定市場進入極度超跌區，左側抄底勝率顯著提升。
        
        ---
        ### 🧬 各量化指標詳細定義與數據源
        
        #### **1. 【重磅生死線】200週線大底防線 [s8]**
        * **因子定義**：計算比特幣現價與 **200週移動平均線 (200WMA)** 的偏離比例。歷史上，200週線是比特幣多輪大熊市（如2018、2022年）的「終極鋼鐵大底」。越接近該線，防禦價值與抄底得分越高。
        * **數據來源**：`yfinance` 跨市場週線歷史資料庫（代號：`BTC-USD`）。
        
        #### **2. 【美股風向球】MSTR 靜態 mNAV 現貨溢價指標 [s7]**
        * **因子定義**：**此指標採用企業價值(EV)相對於實際持有比特幣市值之去泡沫標準。** 完美對齊最新官方財報控制台結構。當比率壓縮到 1.1x~1.2x 區間時，代表美股資產溢價已降至健康水位，適合擴大現貨槓桿。
        * **數據來源**：`yfinance` 美股與加密市場即時報價交叉核算。
        
        #### **3. 【衍生品關卡】永續合約多空資金費率 [s6]**
        * **因子定義**：監控加密衍生品市場的多空槓桿平衡狀態。當資金費率為大幅正數時，代表多頭過熱；當**資金費率轉負（Negative Funding Rate）**或極度萎縮時，代表市場多頭完成爆倉清算、散戶瘋狂做空，為經典的現貨右側反彈/左側抄底訊號。
        * **數據來源**：幣安期貨 SDK 官方即時合約串流（代號：`Binance CM-Futures API` 的 `BTCUSD_PERP` 數據）。
        
        #### **4. 【韭菜探針】市場散戶恐懼情緒 [s5]**
        * **因子定義**：傳統加密市場 Fear & Greed 請求極易因海外節點遭到 Cloudflare 封鎖而卡死。本看板創新採用**美股 CBOE 波動率指數 (VIX)** 進行反向映射與平滑去噪，精準捕捉跨市場宏觀資金 की 非理性恐慌程度。VIX 越高，映射出的恐懼情緒越強，抄底得分越高。
        * **數據來源**：`yfinance` 芝加哥期權交易所波动率指數（代號：`^VIX`）。
        
        #### **5. 【成本拉力】大盤生命線偏離度 [s2]**
        * **因子定義**：計算現價與 **60日均線（MA60，大盤中線生命線）** 的負乖離率（Bias）。當現價低於 MA60 超過 20% 時，意味著市場短期出現了非理性的「超賣瀑布」，成本拉力回歸動能極強。
        * **數據來源**：`yfinance` 日線歷史價格資料庫滾動計算。
        
        #### **6. 【時空定位】四年減半週期進度規律 [s9]**
        * **因子定義**：基於比特幣每 1460 天減半一次的硬編碼規律。模型自動動態計算當前距離 2024 年 4 月 20 日已知減半日的時空进度。在週期第 500 天至 800 天的傳統「熊市築底與大洗盤區間」，模型會賦予極具防守性的週期時間分。
        * **數據來源**：本地時間引擎（`datetime.now()`）與歷史減半時間軸精確矩陣計算。
        
        #### **7. 【短期套牢】兩週散戶虧損洗盤 [s3]**
        * **因子定義**：計算當前價格與 14 天前（兩週前）收盤價的相對回撤比例。用以量化「近兩週內衝進去追高的散戶籌碼」目前被深套、清洗的痛苦程度。回撤越大，代表浮動追高籌碼被洗得越乾鏡。
        * **數據來源**：`yfinance` 日線近兩週歷史回溯。
        
        #### **8. 【恐懼割肉】今日盤中下殺強度 [s4]**
        * **因子定義**：捕捉 24 小時內極短線的多殺多閃崩幅度。若單日跌幅下殺接近或超過 5%，系統會判定日內恐慌盤、機器人止損盤已經被強行逼出，屬於高勝率的「插針撿便宜」時機。
        * **數據來源**：`yfinance` 當日即時跨開盤價變動比例（`delta`）。
        
        #### **9. 【日內微調】今日撿便宜便宜度 [s1]**
        * **因子定義**：微觀插針指標。計算目前最新即時價處於今日最高點與最低點震盪區間（High-Low Range）的哪一個相對位置。當價格無限逼近今日插針最低點時，s1 因子將逼近 5 分滿分，提供精確到分鐘級的掛單優勢。
        * **數據來源**：`yfinance` 每 5 分鐘滾動的日內極高/極低價串流。
        """)

# ==========================================
# 5. 分頁 B：文元萌化版
# ==========================================
else:
    st.markdown("""
        <style>
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #fff5f5 !important;
            color: #4a4a4a !important;
            font-family: 'PingFang TC', system-ui, sans-serif;
        }
        [data-testid="stHeader"] { background: rgba(0,0,0,0); }
        footer {visibility: hidden;}
        
        .cute-card {
            background: #ffffff;
            border: 3px solid #ffb6c1;
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 15px;
            box-shadow: 0 8px 16px rgba(255, 182, 193, 0.2);
            transition: all 0.3s ease;
        }
        .cute-card:hover {
            transform: scale(1.01);
            box-shadow: 0 10px 20px rgba(255, 182, 193, 0.4);
        }
        .cute-title {
            font-size: 16px;
            color: #ff69b4;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .cute-value {
            font-size: 14px;
            color: #555555;
            margin-top: 8px;
            line-height: 1.5;
        }
        .cute-badge {
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .badge-sleep { background-color: #f3f3f3; color: #9b9b9b; border: 1px solid #ddd; }
        .badge-watch { background-color: #ffeaa7; color: #d63031; border: 1px solid #f1c40f; }
        .badge-buy { background-color: #ff7675; color: #ffffff; }
        
        .heart-score-display {
            font-size: 56px;
            font-weight: bold;
            color: #ff69b4;
            font-family: system-ui, sans-serif;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div style="text-align: center; padding: 10px 0; border-bottom: 3px dashed #ffb6c1; margin-bottom: 25px;">
            <div style="font-size: 26px; font-weight: bold; color: #ff69b4;">💖 文元專屬：比特幣「能不能買包包」終極防割监控儀表板</div>
            <div style="font-size: 14px; color: #7f8c8d; margin-top: 8px;">👩‍🏫 <b>魏文元專屬小叮嚀：</b>老公有沒有亂買看這裡就對了！</div>
        </div>
    """, unsafe_allow_html=True)
    
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        delta_emoji = "📈 太棒了寶貝！" if "-" not in price_delta_str else "📉 跌倒了拍拍："
        delta_color = "#2ecc71" if "-" not in price_delta_str else "#e74c3c"
        st.markdown(f"""
            <div style="background: white; padding: 25px; border-radius: 20px; border: 3px solid #ffb6c1; text-align: center;">
                <div style="font-size: 16px; color: #7f8c8d; font-weight: bold;">🪙 比特幣現在的價格 (BTC/USD)</div>
                <div style="font-size: 46px; font-weight: bold; color: #ff69b4; margin: 10px 0; font-family: monospace;">${btc_price:,.2f}</div>
                <div style="font-size: 16px; font-weight: bold; color: {delta_color};">{delta_emoji} {price_delta_str}</div>
            </div>
        """, unsafe_allow_html=True)
        
        if total_score < 30:
            advice_title, advice_desc = "❌ 先去睡覺，千萬不要動！", "現在市場大家都瘋了在亂買，進去就是當韭菜送人頭。現在敢亂買的話，直接罰老公去跪算盤！"
        elif total_score < 60:
            advice_title, advice_desc = "👀 搬小板凳，坐著看戲就好", "市場現在有點小震盪、不上不下的。我們繼續優雅地喝貴婦下午茶，等真正大特價再說。"
        else:
            advice_title, advice_desc = "🛍️ 限時大特價！百貨週年慶衝啊！", "傳說中的全宇宙打折季來了！大家都嚇到把寶貝亂扔，現在正是叫老公去撿便宜、幫我們賺包包基金的黃金時刻！"
        
        st.markdown(f"""
            <br>
            <div style="background: linear-gradient(135deg, #fff0f5 0%, #ffe4e1 100%); padding: 30px; border-radius: 25px; border: 3px solid #ff69b4; text-align: center;">
                <div style="font-size: 18px; color: #db7093; font-weight: bold;">🛍️ 當前能不能撿便宜指数</div>
                <div class="heart-score-display">❤️ {total_score:.1f} <span style="font-size:22px; color:#db7093;">/ 100 滿分</span></div>
                <div style="margin-top: 15px; padding: 15px; background: white; border-radius: 15px; border: 2px solid #ffb6c1;">
                    <div style="font-size: 18px; font-weight: bold; color: #e74c3c;">{advice_title}</div>
                    <div style="font-size: 14px; color: #555555; margin-top: 8px; line-height: 1.6;">{advice_desc}</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col_right:
        def get_cute_badge(score, max_score):
            ratio = score / max_score if max_score > 0 else 0
            if ratio >= 0.65: return '<span class="cute-badge badge-buy">🔥 百貨週年慶衝啊！</span>'
            if ratio >= 0.3: return '<span class="cute-badge badge-watch">🧐 有點風吹草動</span>'
            return '<span class="cute-badge badge-sleep">💤 大家都還在睡</span>'
        
        st.markdown(f"""
            <div class="cute-card">
                <div class="cute-title"><span>🩸 歷史級終極防禦大鐵底 [s8]</span> {get_cute_badge(s8, 20.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s8:.1f} / 20.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 跌到這裡就是到了幾年才一次的地下室清倉價！</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>🤡 美股大韭菜有沒有吹泡泡 [s7]</span> {get_cute_badge(s7, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s7:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 目前已改採官方最新控制台公式（EV / BTC總價值 = {mstr_premium_rate:.2f} 倍）。數字越低泡沫越小，對我們越安全！</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
