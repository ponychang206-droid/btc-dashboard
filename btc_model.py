import streamlit as st
import yfinance as yf
from datetime import datetime

# ==========================================
# 1. 核心參數輸入 (請根據最新公告手動更新)
# ==========================================
st.sidebar.header("MSTR 核心參數配置")
ADSO = st.sidebar.number_input("流通股數 (ADSO Millions)", value=386.052)
TOTAL_DEBT = st.sidebar.number_input("總負債 ($M)", value=6714)
TOTAL_PREF = st.sidebar.number_input("特別股 ($M)", value=15471)
CASH = st.sidebar.number_input("現金儲備 ($M)", value=1100)
MSTR_BTC = st.sidebar.number_input("BTC 總持倉", value=846842)
OFFICIAL_MNAV = st.sidebar.number_input("官方 mNAV 數值 (手動輸入)", value=1.21)

# ==========================================
# 2. 即時數據抓取
# ==========================================
@st.cache_data(ttl=60)
def get_live_data():
    mstr = yf.Ticker("MSTR")
    mstr_price = float(mstr.history(period="1d")['Close'].iloc[-1])
    btc = yf.Ticker("BTC-USD")
    btc_price = float(btc.history(period="1d")['Close'].iloc[-1])
    return mstr_price, btc_price

price, btc = get_live_data()

# ==========================================
# 3. 五大指標計算引擎
# ==========================================
# A. 官方 mNAV (作為基準)
official_nmav = OFFICIAL_MNAV

# B. 單純 ADSO 去泡沫化 mNAV (指標 1)
# 公式: (BTC市值) / (ADSO * Price)
btc_market_val = (MSTR_BTC * btc) / 1_000_000
adso_nmav_premium = (ADSO * price) / btc_market_val

# C. 企業價值 EV 溢價 (指標 2)
# EV = (ADSO * Price) + Pref + Debt - Cash
ev = (ADSO * price) + TOTAL_PREF + TOTAL_DEBT - CASH
ev_premium = ev / btc_market_val

# D. 債務安全邊際 (指標 3)
# (BTC市值 - 總負債) / BTC市值
debt_margin = (btc_market_val - TOTAL_DEBT) / btc_market_val

# E. BTC 每股含幣量 (指標 4)
bps = MSTR_BTC / (ADSO * 1_000_000)

# F. 與 BTC 相關性乖離 (指標 5 - 簡化版)
# 這裡簡單呈現 Price / BTC 比值作為乖離趨勢
corr_deviation = price / btc

# ==========================================
# 4. 監控儀表板 UI
# ==========================================
st.title("🛡️ MSTR 深度監控儀表板")

# 第一行：核心比價
col1, col2, col3 = st.columns(3)
col1.metric("MSTR 現價", f"${price:.2f}")
col2.metric("官方 mNAV", f"{official_nmav}x")
col3.metric("ADSO 真實溢價", f"{adso_nmav_premium:.2f}x")

# 第二行：進階指標
st.markdown("---")
row2 = st.columns(4)
row2[0].metric("企業 EV 溢價", f"{ev_premium:.2f}x")
row2[1].metric("債務安全邊際", f"{debt_margin:.1%}")
row2[2].metric("每股含幣量 (Sats)", f"{bps * 100_000_000:,.0f}")
row2[3].metric("價格乖離率", f"{corr_deviation:.5f}")

# 警示燈
if adso_nmav_premium < 1.0:
    st.error("🚨 警告：ADSO 溢價已低於 1.0，進入資產清算折價區！")
elif adso_nmav_premium > 2.0:
    st.warning("⚠️ 警告：溢價過高，市場情緒過熱。")

st.info(f"更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
