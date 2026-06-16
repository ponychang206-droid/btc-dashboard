import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 側邊欄參數設置 ---
st.sidebar.header("⚙️ MSTR 核心參數配置")
# 使用您截圖中的最新數據作為預設值
ADSO = st.sidebar.number_input("流通股數 (ADSO Millions)", value=386.052)
TOTAL_DEBT = st.sidebar.number_input("總負債 ($M)", value=6754)
TOTAL_PREF = st.sidebar.number_input("特別股 ($M)", value=15475)
CASH = st.sidebar.number_input("現金儲備 ($M)", value=1100)
MSTR_BTC = st.sidebar.number_input("BTC 總持倉", value=846842)

# --- 數據獲取 ---
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

# --- 計算核心引擎 ---
btc_reserve_m = (MSTR_BTC * btc) / 1_000_000 # BTC Reserve ($M)
market_cap_m = ADSO * price                 # 市值 ($M)
ev = market_cap_m + TOTAL_PREF + TOTAL_DEBT - CASH # EV = 市值+特別股+債-現金

# 五大指標
official_mnav = ev / btc_reserve_m          # 依照您的定義：EV / BTC Reserve
adso_nmav = market_cap_m / btc_reserve_m    # ADSO 去泡沫 mNAV
ev_premium = ev / btc_reserve_m             # 與官方 mNAV 同義
debt_margin = (btc_reserve_m - TOTAL_DEBT) / btc_reserve_m
bps = MSTR_BTC / (ADSO * 1_000_000)
price_dev = price / btc

# --- 呈現儀表板 ---
st.title("🛡️ MSTR 深度分析監控儀表板")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("MSTR 現價", f"${price:.2f}")
col2.metric("官方 mNAV (EV/Res)", f"{official_mnav:.2f}x")
col3.metric("ADSO 溢價", f"{adso_nmav:.2f}x")
col4.metric("乖離率", f"{price_dev:.5f}")
col5.metric("每股含幣量", f"{bps*1e8:.0f} sats")

st.markdown("---")
st.subheader("📊 指標詳細定義")
data = {
    "指標名稱": ["官方 mNAV", "ADSO 去泡沫 mNAV", "EV 溢價", "債務安全邊際", "價格乖離率"],
    "分子 (Numerator)": ["企業價值 (EV)", "市值 (ADSO * Price)", "企業價值 (EV)", "(BTC Reserve - Debt)", "MSTR 股價"],
    "分母 (Denominator)": ["BTC Reserve ($M)", "BTC Reserve ($M)", "BTC Reserve ($M)", "BTC Reserve ($M)", "BTC 現貨價格"],
    "定義說明": [
        "企業價值相對於比特幣儲備的倍數", 
        "市值相對於比特幣儲備的倍數", 
        "考慮債務與特別股後的總體企業併購溢價", 
        "資產扣除負債後的剩餘緩衝", 
        "股價相對 BTC 的價格情緒偏離"
    ]
}
st.table(pd.DataFrame(data))
