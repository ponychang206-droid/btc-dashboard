import streamlit as st
import yfinance as yf
from datetime import datetime

# ==========================================
# 1. 核心參數輸入區 (根據您提供的最新截圖)
# ==========================================
st.sidebar.header("MSTR 企業價值輸入 (手動更新)")
# 參考您的截圖數據
ADSO_MILLIONS = st.sidebar.number_input("流通股數 (ADSO in millions)", value=386.052)
TOTAL_DEBT_M = st.sidebar.number_input("總負債 (Total Debt $M)", value=6714)
TOTAL_PREF_M = st.sidebar.number_input("特別股 (Preferred Stock $M)", value=15471)
CASH_RESERVE_M = st.sidebar.number_input("現金儲備 (USD Reserve $M)", value=1100)
MSTR_BTC_HOLDINGS = st.sidebar.number_input("BTC 總持倉", value=846842)

# ==========================================
# 2. 即時數據抓取
# ==========================================
def get_live_data():
    mstr = yf.Ticker("MSTR")
    mstr_price = float(mstr.history(period="1d")['Close'].iloc[-1])
    btc = yf.Ticker("BTC-USD")
    btc_price = float(btc.history(period="1d")['Close'].iloc[-1])
    return mstr_price, btc_price

mstr_price, btc_price = get_live_data()

# ==========================================
# 3. 企業價值 (EV) 計算引擎
# ==========================================
# EV = (ADSO * Price) + Pref + Debt - Cash
market_cap_m = ADSO_MILLIONS * mstr_price
ev = market_cap_m + TOTAL_PREF_M + TOTAL_DEBT_M - CASH_RESERVE_M

# BTC 持倉市值 (估算)
btc_value_m = (MSTR_BTC_HOLDINGS * btc_price) / 1_000_000

# 去泡沫真實 mNAV (使用 EV 邏輯)
# 核心邏輯：EV 與 BTC 持倉市值的比率
ev_btc_ratio = ev / btc_value_m

# ==========================================
# 4. 儀表板呈現
# ==========================================
st.title("🛡️ MSTR 機構級企業價值監控")

col1, col2, col3 = st.columns(3)
col1.metric("MSTR 市價", f"${mstr_price:,.2f}")
col2.metric("計算後 EV ($M)", f"${ev:,.0f}")
col3.metric("EV / BTC 持倉比", f"{ev_btc_ratio:.2f}x")

st.markdown("---")
st.subheader("💡 指標分析")
st.write(f"當前市場對 MSTR 的溢價倍數為 **{ev_btc_ratio:.2f}x**。")
st.write("若此數值 > 2.0x，代表市場對 MSTR 的資產溢價過高；若 < 1.0x，代表資產被低估。")
