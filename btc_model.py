import requests
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime

# ==========================================
# 0. 網頁全域設定 (必須是第一個執行的 Streamlit 語法！)
# ==========================================
st.set_page_config(
    page_title="BTC 抄底監控戰情室",
    layout="wide",
    initial_sidebar_state="expanded"  # 強制初始展開側邊欄，讓太太一眼看到
)

# ==========================================
# 1. 數據抓取模組 (保持原有高效邏輯)
# ==========================================
@st.cache_data(ttl=5)
def fetch_binance_ticker():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
        res = requests.get(url, timeout=3).json()
        return {
            'price': float(res['lastPrice']),
            'high': float(res['highPrice']),
            'low': float(res['lowPrice']),
            'delta': float(res['priceChangePercent'])
        }
    except:
        return None

@st.cache_data(ttl=5)
def fetch_funding_rate():
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        res = requests.get(url, timeout=3).json()
        return float(res['lastFundingRate'])
    except:
        return 0.0001

@st.cache_data(ttl=30)
def fetch_historical_data():
    try:
        url_d = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=100"
        res_d = requests.get(url_d, timeout=5).json()
        daily_closes = [float(k[4]) for k in res_d]
        
        url_w = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1w&limit=1000"
        res_w = requests.get(url_w, timeout=5).json()
        
        dates_w = [datetime.fromtimestamp(k[0]/1000) for k in res_w]
        closes_w = [float(k[4]) for k in res_w]
        
        df_w = pd.DataFrame({'Date': dates_w, 'Close': closes_w})
        df_w['200WMA'] = df_w['Close'].rolling(window=200).mean()
        
        return daily_closes, df_w
    except:
        return [], pd.DataFrame()

@st.cache_data(ttl=30)
def fetch_fear_greed():
    try:
        res = requests.get("https://api.alternative.me/fng/?limit=1", timeout=3).json()
        return int(res['data'][0]['value'])
    except:
        return 50

@st.cache_data(ttl=60)
def fetch_mstr_premium():
    try:
        mstr = yf.Ticker("MSTR")
        mstr_price = mstr.fast_info['last_price']
        return mstr_price
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
    
    # s7: MSTR 預估 mNAV 溢價指標
    if mstr_live_price is not None:
        estimated_nav = (btc_price * 0.0012) 
        mstr_premium_rate = mstr_live_price / estimated_nav if estimated_nav > 0 else 1.5
        s7 = max(0.0, min(15.0, ((2.5 - mstr_premium_rate) / 1.5) * 15.0))
    else:
        s7 = 7.5
        
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
# 3. 側邊欄切換路由 (獨立出來確保必定渲染)
# ==========================================
with st.sidebar:
    st.markdown("### 🔮 戰情室切換")
    page = st.radio(
        "請選擇檢視視角：",
        ["直男量化經理人版", "文元專屬：能不能買包包版"],
        index=0
    )
    st.markdown("---")
    st.markdown("💡 *小提示：點選上方選項即可切換專業黑客風或粉紅萌化版介面！*")

# ==========================================
# 4. 分頁 A：直男量化經理人版
# ==========================================
if page == "直男量化經理人版":
    # 注入原始自訂高級感深色主題 CSS
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
        
        .whitepaper-block {
            background-color: #181a20;
            border: 1px solid #2b3139;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
        }
        .whitepaper-tag {
            background: rgba(243, 186, 47, 0.12);
            color: #f3ba2f;
            padding: 3px 10px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 13px;
            font-weight: bold;
            margin-right: 10px;
        }
        .whitepaper-title { font-size: 16px; font-weight: 700; color: #eaecef; }
        .whitepaper-text { font-size: 14px; color: #b7bdc6; line-height: 1.6; margin-top: 10px; }
        .whitepaper-subtext {
            font-size: 12px;
            color: #848e9c;
            margin-top: 6px;
            background: #111417;
            padding: 6px 12px;
            border-radius: 6px;
            border-left: 3px solid #474d57;
        }
        </style>
    """, unsafe_allow_html=True)

    # 頂部戰情室抬頭
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #2b3139; margin-bottom: 25px;">
            <div style="font-size: 24px; font-weight: 700; color: #eaecef; display: flex; align-items: center; gap: 10px;">
                <span style="color: #f3ba2f;">🔮</span> BTC 9 因子抄底監控看板 (量化經理人加權版)
            </div>
            <div style="font-size: 12px; color: #848e9c; text-align: right;">
                系統狀態：<span style="color: #0ecb81; font-weight: bold;">● 即時串流中</span><br>
                更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([1.1, 1])

    with col_left:
        delta_color = "#0ecb81" if "-" not in price_delta_str else "#f6465d"
        st.markdown(f"""
            <div style="background: #181a20; padding: 20px; border-radius: 12px; border: 1px solid #2b3139; margin-bottom: 20px;">
                <div style="font-size: 13px; color: #848e9c; font-weight: 500; text-transform: uppercase; letter-spacing: 1px;">幣安現貨即時報價 (BTC/USDT)</div>
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
            <div class="metric-card"><div class="metric-title"><span>【美股風向球】MSTR 預估 mNAV 溢價指標 [s7] (權重: 15%)</span> {get_ui_badge(s7, 15.0)}</div><div class="metric-value">{s7:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前美股溢價估算: {mstr_premium_rate:.2f} 倍</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【衍生品關卡】合約多空資金費率 [s6] (權重: 15%)</span> {get_ui_badge(s6, 15.0)}</div><div class="metric-value">{s6:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前即時資金費率: {funding_rate*100:+.4f}%</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【韭菜探針】市場散戶恐懼情緒 [s5] (權重: 15%)</span> {get_ui_badge(s5, 15.0)}</div><div class="metric-value">{s5:.1f} / 15.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">當前恐懼貪婪讀數: {fng_value}</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【成本拉力】大盤生命線偏離度 [s2] (權重: 10%)</span> {get_ui_badge(s2, 10.0)}</div><div class="metric-value">{s2:.1f} / 10.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">離 60 日均線的負乖離比例</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【時空定位】四年減半週期進度規律 [s9] (權重: 10%)</span> {get_ui_badge(s9, 10.0)}</div><div class="metric-value">{s9:.1f} / 10.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">長線歷史週期時間節點定位</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【短期套牢】兩週散戶虧損洗盤 [s3] (權重: 5%)</span> {get_ui_badge(s3, 5.0)}</div><div class="metric-value">{s3:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">14天追高籌碼被清洗程度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【恐懼割肉】今日盤中下殺強度 [s4] (權重: 5%)</span> {get_ui_badge(s4, 5.0)}</div><div class="metric-value">{s4:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">24小時內多殺多閃崩幅度</span></div></div>
            <div class="metric-card"><div class="metric-title"><span>【日內微調】今日撿便宜便宜度 [s1] (權重: 5%)</span> {get_ui_badge(s1, 5.0)}</div><div class="metric-value">{s1:.1f} / 5.0 分 <span style="font-size:12px; color:#848e9c; font-weight:normal; margin-left:10px;">市價接近今日插針最低點鄰近度</span></div></div>
        """, unsafe_allow_html=True)

    # 底部白皮書說明
    st.write("")
    st.write("")
    st.markdown('<div style="background: #181a20; padding: 15px; border-radius: 8px; border-left: 4px solid #f3ba2f; margin-bottom: 25px;"><h3 style="margin:0; font-size:18px; color:#eaecef; font-weight:700;">🔍 量化防禦指標說明白皮書 (深度核心邏輯與配置規範)</h3></div>', unsafe_allow_html=True)
    
    st.markdown(f"""
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s8 (20%)</span><span class="whitepaper-title">【重磅生死線】200週移動平均線 (200WMA)</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>統計比特幣過去 200 週（近 4 年）的週收盤均價。在加密貨幣歷史週期中，200WMA 被視為長期機構與巨鯨囤餅的「神聖生死底線」。除非發生全球系統性金融海嘯，否則價格極難有效跌破此線。當現價高度逼近、持平、或意外跌破 200WMA 時，本因子得分將迅速拉滿，觸發歷史級別的絕對左側抄底訊號。</div><div class="whitepaper-subtext">📡 數據來源：Binance 全球歷史 K 線資料庫 (呼叫現貨週收盤價滾動計算法)</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s7 (15%)</span><span class="whitepaper-title">【美股風向球】微策略 MSTR 預估 mNAV 溢價指標</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>追蹤 MicroStrategy (MSTR) 在美股市場的實際市值，對比其資產負債表上比特幣總持倉淨資產（NAV）的溢價倍數。當溢價率過高（例如 >2.5 倍）時，意味著美股衍生資產充斥著極高溢價泡沫；而當溢價率大幅回落至 1.0 附近，或甚至貼近淨資產時，表明傳統金融機構的恐懼踩踏已經見底。溢價率越低，本因子得分越高，代表美股端的槓桿與泡沫已清洗乾淨。</div><div class="whitepaper-subtext">📡 數據來源：Yahoo Finance (MSTR 實時股價) 連動 Binance 現貨計算</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s6 (15%)</span><span class="whitepaper-title">【衍生品關卡】永續合約期貨多空資金費率</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>即時監控合約市場多頭與空頭的槓桿成本。當市場瘋狂追多時，資金費率呈現高昂正值（如 >+0.05%）；當市場陷入絕望、集體瘋狂做空或多頭遭到連環清算（Long Squeeze）時，費率會迅速插針轉為「負費率」。當資金費率轉負或低於基礎利率（0.01%）時，代表空頭嚴重過載，此時爆空（Short Squeeze）引發強彈的機率極高，因子得分會依據負值深度呈線性暴增。</div><div class="whitepaper-subtext">📡 數據來源：Binance Futures API (每 5 秒即時滾動追蹤最新合約資金費率)</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s5 (15%)</span><span class="whitepaper-title">【韭菜探針】Crypto 全網散戶恐懼貪婪情緒指數</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>整合全網社交媒體音量、波動率、市場動量、以及搜尋趨勢的散戶大眾反向情緒指標。量化引擎的核心哲學是「在他人恐懼時我貪婪」。當情緒指數跌破 20 進入「極度恐懼（Extreme Fear）」區間時，意味著散戶籌碼正在絕望割肉，市場已經接近情緒底。指數讀數越低，本因子的防禦抄底得分就會越高。</div><div class="whitepaper-subtext">📡 數據來源：Alternative.me 官方即時情緒指標 API</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s2 (10%)</span><span class="whitepaper-title">【成本拉力】MA60 趨勢生命線負乖離</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>計算當前比特幣價格相對於 60 日中期成本均線（大盤生命線）的偏離幅度。當價格因為短線非理性暴跌，導致遠遠低於 60 日均線時，會產生極強的「均值回歸（Mean Reversion）」拉力。量化模型設定：當負乖離（Bias）接近或超過 -20% 時，代表短線超賣極其嚴重，因子得分將逼近 10 分滿分。</div><div class="whitepaper-subtext">📡 數據來源：Binance Klines 日線級別滾動計算</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s9 (10%)</span><span class="whitepaper-title">【時空定位】四年減半週期時空推進進度</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>依據比特幣代碼底層每 210,000 個區塊（約 1460 天）減半一次的歷史鐵律進行時空定位。歷史規律表明，減半後的 500 到 800 天通常是市場尋找長線大底或步入週期中後段调整的關鍵洗盤期。模型會根據當前距離最新減半日（2024年4月20日）的時間跨度，精確計算時間維度的抄底安全係數，為資產配置提供宏觀的時間軸保護。</div><div class="whitepaper-subtext">📡 數據來源：系統內置時間戳核心計算引擎</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s3 (5%)</span><span class="whitepaper-title">【短期套牢】14天散戶浮虧洗盤強度</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>屬於中期微調因子，回溯並比較當前現價與 14 天前價格的相對跌幅。若兩週內遭遇連續重挫，代表在近期高點進場的短線投機籌碼全部陷入深度浮虧狀態。當投機籌碼經歷非理性連環洗盤，市場通常會迎來短期賣壓耗盡的反彈拐點。14天內跌幅越深，此項得分越高。</div><div class="whitepaper-subtext">📡 數據來源：Binance 兩週滾動日線收盤價</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s4 (5%)</span><span class="whitepaper-title">【恐懼割肉】今日盤中瀑布下殺強度</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>即時監控過去 24 小時內的最高價與現價跌幅。此指標專門用來捕捉日內突發性的「恐懼閃崩（Flash Crash）」，例如黑天鵝事件引發的交易所多頭強平潮。當盤中出現極端下殺、跌幅超過 5% 以上時，量化模型會判定此為日內微觀插針的絕佳左側接刀時機，隨即分配高分數。</div><div class="whitepaper-subtext">📡 數據來源：Binance Ticker 24hr 即時行情數據</div></div>
        <div class="whitepaper-block"><div style="display:flex; align-items:center;"><span class="whitepaper-tag">s1 (5%)</span><span class="whitepaper-title">【日內微調】今日撿便宜便宜度 (盤中插針鄰近度)</span></div><div class="whitepaper-text"><strong>核心量化邏輯：</strong>微觀執行層面的分時控筆指標。即時計算當前現貨價格在今天日內最高點與最低點區間（High-Low Range）所處的相對位置。當市價高度貼近今天盤中最低點時，說明日內下殺力道可能暫時耗盡、買盤開始在低位托底，此時接單能拿到今天極具優勢的微觀成本價，得分拉滿。</div><div class="whitepaper-subtext">📡 數據來源：Binance Ticker 實時高低價廣播</div></div>
    """, unsafe_allow_html=True)

# ==========================================
# 5. 分頁 B：文元萌化版
# ==========================================
else:
    # 專屬粉紅萌系 CSS 注入
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
    
    # 萌系頁頭
    st.markdown("""
        <div style="text-align: center; padding: 10px 0; border-bottom: 3px dashed #ffb6c1; margin-bottom: 25px;">
            <div style="font-size: 26px; font-weight: bold; color: #ff69b4;">💖 文元專屬：比特幣「能不能買包包」終極防割監控儀表板</div>
            <div style="font-size: 14px; color: #7f8c8d; margin-top: 8px;">👩🏻‍🏫 <b>魏文元專屬小叮嚀：</b>老公有沒有亂買看這裡就對了！</div>
        </div>
    """, unsafe_allow_html=True)
    
    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        # 可愛版即時幣價
        delta_emoji = "📈 太棒了寶貝！" if "-" not in price_delta_str else "📉 跌倒了拍拍："
        delta_color = "#2ecc71" if "-" not in price_delta_str else "#e74c3c"
        st.markdown(f"""
            <div style="background: white; padding: 25px; border-radius: 20px; border: 3px solid #ffb6c1; text-align: center;">
                <div style="font-size: 16px; color: #7f8c8d; font-weight: bold;">🪙 比特幣現在的價格 (BTC/USDT)</div>
                <div style="font-size: 46px; font-weight: bold; color: #ff69b4; margin: 10px 0; font-family: monospace;">${btc_price:,.2f}</div>
                <div style="font-size: 16px; font-weight: bold; color: {delta_color};">{delta_emoji} {price_delta_str}</div>
            </div>
        """, unsafe_allow_html=True)
        
        # 依據總得分給出白話買包包建議
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
        
        # 白話萌化版 4 大核心因子卡片
        st.markdown(f"""
            <div class="cute-card">
                <div class="cute-title"><span>🩸 歷史級終極防禦大鐵底 [s8]</span> {get_cute_badge(s8, 20.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s8:.1f} / 20.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：跌到這裡就是到了幾年才一次的地下室清倉價！巨鯨都在這偷偷買，非常安全。</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>🤡 美股大韭菜有沒有吹泡泡 [s7]</span> {get_cute_badge(s7, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s7:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：看美股微策略（MSTR）有沒有把泡沫吹太大（目前溢價：{mstr_premium_rate:.2f} 倍）。數字越低代表美股那邊的笨蛋洗乾淨了。</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>💥 全網賭徒有沒有被抬出去 [s6]</span> {get_cute_badge(s6, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s6:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：看那些開槓桿的賭徒是不是都在哭。當賭徒都被斷頭清光（資金費率變低或變負），就是我們進場撿便宜的訊號。</span>
                </div>
            </div>
            
            <div class="cute-card">
                <div class="cute-title"><span>😱 全網散戶是不是嚇到發抖 [s5]</span> {get_cute_badge(s5, 15.0)}</div>
                <div class="cute-value">
                    <b>特價得分：{s5:.1f} / 15.0 滿分</b><br>
                    <span style="color:#7f8c8d; font-size:13px;">💡 白話文解釋：大眾恐懼指數（當前讀數：{fng_value}）。全網散戶越害怕割肉、嚇得哇哇叫，分數就越高，我們就要在旁邊偷偷笑。</span>
                </div>
            </div>
        """, unsafe_allow_html=True)
