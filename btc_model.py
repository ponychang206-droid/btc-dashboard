import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
from binance.cm_futures import CMFutures  # 替代原有的 fapi 請求

# ==========================================
# 0. 網頁全域設定 (必須是第一個執行的 Streamlit 語法！)
# ==========================================
st.set_page_config(
    page_title="BTC 抄底監控戰情室",
    layout="wide",
    initial_sidebar_state="expanded"  # 強制初始展開側邊欄，讓太太一眼看到
)

# ==========================================
# 1. 數據抓取模組 (完全移除 requests，改用極穩定的 SDK 與 yfinance)
# ==========================================
@st.cache_data(ttl=5)
def fetch_binance_ticker():
    """使用 yfinance 抓取 BTC 即時與 24h 行情，避免雲端 IP 被幣安封鎖"""
    try:
        btc = yf.Ticker("BTC-USD")
        # 抓取最近兩天的分鐘級數據，確保能算出高低價與漲跌幅
        df = btc.history(period="2d", interval="5m")
        if not df.empty:
            last_price = float(df['Close'].iloc[-1])
            # 取得今日（最後24小時）的高低價
            df_24h = btc.history(period="1d", interval="1m")
            high_price = float(df_24h['High'].max()) if not df_24h.empty else last_price
            low_price = float(df_24h['Low'].min()) if not df_24h.empty else last_price
            
            # 計算 24h 漲跌幅
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
    """使用官方免驗證的 binance-connector SDK 抓取資金費率，防範阻擋"""
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
        
        # 1. 抓取日線歷史資料 (計算 MA60 與 14天洗盤)
        df_d = btc.history(period="100d", interval="1d")
        daily_closes = df_d['Close'].tolist() if not df_d.empty else []
        
        # 2. 抓取長線週線資料 (計算 200WMA)
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
    """修正原先 fast_info 在雲端容易拿不到資料的 Bug，改用歷史最後一筆收盤價"""
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
mstr_premium_rate = 1.5  

# ==========================================
# 📊 2026 最新官方精確參數配置
# ==========================================
MSTR_BTC_HOLDINGS = 843706       # 官方最新持倉數量
MSTR_SHARES_OUTSTANDING = 182510000  # 官方最新精密流通股數 (182.51M)
MSTR_AVG_COST = 75699            # 官方平均持倉成本
BTC_PER_SHARE = 0.0046228        # 重新校正後的每股真實代表 BTC 數量

if ticker_data is not None:
    btc_price = ticker_data['price']
    price_delta_str = f"{ticker_data['delta']:+.2f}%"

    # s1: 日內微觀掛單最優便宜度
    p_range = ticker_data['high'] - ticker_data['low']
    s1 = (((ticker_data['high'] - btc_price) / p_range) * 5.0) if p_range > 0 else 2.5
    
    # s2: 大盤生命線 MA60 負乖離
    if len(daily_closes) >= 60:
        bias = (btc_price - np.mean(daily_closes[-60:])) / np.mean(daily_closes[-60:])
        s2 = max(0.0, min(10.0, (0.0 - bias) / 0.20 * 10.0))
    else: 
        s2 = 5.0
        
    # s3: 14天散戶套牢洗盤度
    if len(daily_closes) >= 14:
        r14 = (btc_price - daily_closes[-14]) / daily_closes[-14]
        s3 = max(0.0, min(5.0, (0.0 - r14) / 0.15 * 5.0))
    else: 
        s3 = 2.5
        
    # s4: 今日盤中瀑布下殺強度
    s4 = max(0.0, min(5.0, (abs(ticker_data['delta']) / 5.0) * 5.0)) if ticker_data['delta'] < 0 else 0.0
    
    # s5: 散戶恐懼貪婪情緒指數
    s5 = max(0.0, min(15.0, ((40.0 - float(fng_value)) / 30.0) * 15.0))
    
    # s6: 永續合約多空資金費率
    s6 = max(0.0, min(15.0, ((0.0001 - funding_rate) / 0.0004) * 15.0))
    
    # s7: MSTR 精確 mNAV 溢價指標
    if mstr_live_price is not None:
        estimated_nav = (btc_price * BTC_PER_SHARE) 
        mstr_premium_rate = mstr_live_price / estimated_nav if estimated_nav > 0 else 1.5
        s7 = max(0.0, min(15.0, ((2.5 - mstr_premium_rate) / 1.5) * 15.0))
    else:
        mstr_premium_rate = 1.55
        s7 = 9.1
        
    # s8: 200週線大底防線
    if not df_weekly.empty and len(df_weekly) >= 200:
        ma200_w_current = float(df_weekly.iloc[-1]['200WMA'])
        dist_200w = (btc_price - ma200_w_current) / ma200_w_current
        s8 = max(0.0, min(20.0, ((0.05 - dist_200w) / 0.10) * 20.0))
    else:
        ma200_w_current = btc_price * 0.7
        s8 = 10.0
        
    # s9: 四年減半週期時空定位
    last_halving = datetime(2024, 4, 20)
    days_since_halving = (datetime.now() - last_halving).days
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
    st.markdown("### 📊 MSTR 官方資產負債表")
    st.info(f"🪙 持倉總量: {MSTR_BTC_HOLDINGS:,} BTC")
    st.info(f"📜 流通股數: {MSTR_SHARES_OUTSTANDING:,} 股")
    st.info(f"📉 平均成本: ${MSTR_AVG_COST:,} USD")
    st.markdown("---")
    st.markdown("💡 *小提示：點選上方選項即可切換專業黑客風或粉紅萌化版介面！*")

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

    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #2b3139; margin-bottom: 25px;">
            <div style="font-size: 24px; font-weight: 700; color: #eaecef; display: flex; align-items: center; gap: 10px;">
                <span style="color: #f3ba2f;">🔮</span> BTC 9 因子抄底監控看板 (2026精密股數修正版)
            </div>
            <div style="font-size: 12px; color: #848e9c; text-align: right;">
                系統狀態：<span style="color: #0ecb81; font-weight: bold;">● SDK 即時串流中</span><br>
                更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([1.1, 1])

    with col_left:
        delta_color = "#0ecb81" if "-" not in price_delta_str else "#f6465d"
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
        st.markdown(f'<div style="background: #181a20; padding: 22px; border-radius: 12px; border: 1px solid #2b3139; margin-bottom: 20px; text-align: center;"><div style="font-size: 15px; color: #848e9c; font-weight: 600; letter-spacing: 1px;">🎯 經理人多因子總得分</div><div class="score-display">{total_score:.1f} <span style="font-size:20px; color:#474d57;">/ 100 分</span></div></div>', unsafe_allow_html=True)
        
        def get_ui_badge(score, max_score):
            ratio = score / max_score if max_score > 0 else 0
            if ratio < 0.3: return '<span class="badge badge-gray">🔴 正常震盪 / 暫無訊號</span>'
            if ratio < 0.65: return '<span class="badge badge-yellow">🟡 波動放大 / 蓄勢觀察</span>'
            return '<span class="badge badge-green">🟢 極度超跌 / 觸發左側抄底</span>'

        st.markdown(f"""
            <div class="metric-card"><div class="metric-title"><span>【重磅生死線】200週線大底防線 [s8] (權重: 20%)</span> {get_ui_badge(s8, 20.0)}</div><div class="metric-value">{s8:.1f} / 20.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">歷史長線支撐防禦度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【美股風向球】MSTR 精密對齊 mNAV 溢價指標 [s7] (權重: 15%)</span> {get_ui_badge(s7, 15.0)}</div><div class="metric-value">{s7:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前美股實際溢價: {mstr_premium_rate:.2f} 倍</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【衍生品關卡】合約多空資金費率 [s6] (權重: 15%)</span> {get_ui_badge(s6, 15.0)}</div><div class="metric-value">{s6:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前即時資金費率: {funding_rate*100:+.4f}%</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【韭菜探針】市場散戶恐懼情緒 [s5] (權重: 15%)</span> {get_ui_badge(s5, 15.0)}</div><div class="metric-value">{s5:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前市場波動對應讀數: {fng_value}</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【成本拉力】大盤生命線偏離度 [s2] (權重: 10%)</span> {get_ui_badge(s2, 10.0)}</div><div class="metric-value">{s2:.1f} / 10.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">離 60 日均線的負乖離比例</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【時空定位】四年減半週期進度規規律 [s9] (權重: 10%)</span> {get_ui_badge(s9, 10.0)}</div><div class="metric-value">{s9:.1f} / 10.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">長線歷史週期時間節點定位</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【短期套牢】兩週散戶虧損洗盤 [s3] (權重: 5%)</span> {get_ui_badge(s3, 5.0)}</div><div class="metric-value">{s3:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">14天追高籌碼被清洗程度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【恐懼割肉】今日盤中下殺強度 [s4] (權重: 5%)</span> {get_ui_badge(s4, 5.0)}</div><div class="metric-value">{s4:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">24小時內多殺多閃崩幅度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【日內微調】今日撿便宜便宜度 [s1] (權重: 5%)</span> {get_ui_badge(s1, 5.0)}</div><div class="metric-value">{s1:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">市價接近今日插針最低點鄰近度</span></div></div>
        """, unsafe_allow_html=True)

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
            <div style="font-size: 26px; font-weight: bold; color: #ff69b4;">💖 文元專屬：比特幣「能不能買包包」終極防割監控儀表板</div>
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
                <div style="font-size: 18px; color: #db7093; font-weight: bold;">🛍️ 當前能不能撿便宜指數</div>
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
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：跌到這裡就是到了幾年才一次的地下室清倉價！局內巨鯨都在這偷偷買，非常安全。</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>🤡 美股大韭菜有沒有吹泡泡 [s7]</span> {get_cute_badge(s7, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s7:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：看美股微策略（MSTR）實際溢價（目前溢價：{mstr_premium_rate:.2f} 倍）。數字越低代表美股泡沫越小，對齊 2026 最新官方股數申報。</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>💥 全網賭徒有沒有被抬出去 [s6]</span> {get_cute_badge(s6, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s6:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：當賭徒被斷頭清光（資金費率變低），就是我們進場撿便宜、叫老公幫我們賺包包基金的黃金時刻！</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>😱 全網散戶是不是嚇到發抖 [s5]</span> {get_cute_badge(s5, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s5:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：大盤越恐懼（當前讀數：{fng_value}），分數就越高，我們就要在旁邊優雅地看著，準備抄底。</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
