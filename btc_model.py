import streamlit as st
import yfinance as yf
import pandas as pd  # 👈 關鍵：必須匯入 pandas
from datetime import datetime

# --- 配置區 ---
st.sidebar.header("⚙️ MSTR 參數設置")
ADSO = st.sidebar.number_input("流通股數 (ADSO Millions)", value=386.052)
TOTAL_DEBT = st.sidebar.number_input("總負債 ($M)", value=6714)
TOTAL_PREF = st.sidebar.number_input("特別股 ($M)", value=15471)
CASH = st.sidebar.number_input("現金儲備 ($M)", value=1100)
MSTR_BTC = st.sidebar.number_input("BTC 總持倉", value=846842)

# --- 數據抓取 ---
@st.cache_data(ttl=60)
def get_live_data():
    try:
        mstr = yf.Ticker("MSTR")
        price = float(mstr.history(period="1d")['Close'].iloc[-1])
        btc = yf.Ticker("BTC-USD")
        btc_price = float(btc.history(period="1d")['Close'].iloc[-1])
        return price, btc_price
    except:
        return 0, 0

price, btc = get_live_data()

# --- 指標計算 ---
btc_market_val = (MSTR_BTC * btc) / 1_000_000
adso_nmav_premium = (ADSO * price) / btc_market_val
ev = (ADSO * price) + TOTAL_PREF + TOTAL_DEBT - CASH
ev_premium = ev / btc_market_val
debt_margin = (btc_market_val - TOTAL_DEBT) / btc_market_val
bps = MSTR_BTC / (ADSO * 1_000_000)
price_deviation = price / btc

# --- 儀表板 ---
st.title("🛡️ MSTR 機構級去泡沫監控")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("MSTR 現價", f"${price:.2f}")
c2.metric("ADSO 溢價", f"{adso_nmav_premium:.2f}x")
c3.metric("EV 溢價", f"{ev_premium:.2f}x")
c4.metric("乖離率", f"{price_deviation:.5f}")
c5.metric("每股含幣量", f"{bps*1e8:.0f} sats")

# --- 修復表格錯誤 ---
st.markdown("---")
st.subheader("📊 指標定義與風險判讀")
data = {
    "指標": ["ADSO 去泡沫 mNAV", "企業價值 EV 溢價", "債務安全邊際", "每股含幣量", "價格乖離率"],
    "定義": ["市值/BTC價值", "EV/BTC價值", "淨資產/BTC市值", "每股 Sats", "股價/BTC價格"],
    "警示": ["<1.0折價, >2.0泡沫", "<1.0折價, >2.5高風險", "<0違約風險", "持續成長為佳", "觀察波動率"]
}
st.table(pd.DataFrame(data)) # 這裡有了 pd 就不會報錯
