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
    initial_sidebar_state="expanded"  # 強制初始展開側邊欄
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

# 📊 2026 最新官方精確參數配置
MSTR_BTC_HOLDINGS = 843706       # 官方最新持倉數量
MSTR_SHARES_OUTSTANDING = 182510000  # 官方最新精密流通股數 (基本股數)
MSTR_AVG_COST = 75699            # 官方平均持倉成本
BTC_PER_SHARE = 0.0046228        # 校正後的每股真實代表 BTC 數量

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
        s8 = max(0.0, min(20.0, ((0.05 - dist_20
