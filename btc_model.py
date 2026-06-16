import streamlit as st
import yfinance as yf
from datetime import datetime

# ==========================================
# ⚠️ 需手動更新的核心數據 (請根據最新公告調整)
# ==========================================
st.sidebar.header("手動更新區 (修正版 mNAV)")
MSTR_BTC_HOLDINGS = st.sidebar.number_input("BTC 總持倉", value=846842)
MSTR_TOTAL_DILUTED_SHARES = st.sidebar.number_input("完全稀釋股數", value=400000000)
MSTR_NET_DEBT = st.sidebar.number_input("淨債務 (USD)", value=4500000000)

# ==========================================
# 1. 自動抓取區
# ==========================================
@st.cache_data(ttl=60)
def get_live_data():
    try:
        mstr = yf.Ticker("MSTR")
        mstr_price = float(mstr.history(period="1d")['Close'].iloc[-1])
        btc = yf.Ticker("BTC-USD")
        btc_price = float(btc.history(period="1d")['Close'].iloc[-1])
        return mstr_price, btc_price
    except:
        return 0, 0

mstr_price, btc_price = get_live_data()

# ==========================================
# 2. 計算引擎 (使用手動輸入的權重)
# ==========================================
# 真實每股清算價值 (去泡沫 mNAV)
real_nav_per_share = ((MSTR_BTC_HOLDINGS * btc_price) - MSTR_NET_DEBT) / MSTR_TOTAL_DILUTED_SHARES
nmav_premium = mstr_price / real_nav_per_share if real_nav_per_share > 0 else 0

# ==========================================
# 3. 監控儀表板
# ==========================================
st.title("🛡️ MSTR 去泡沫真實版監控儀表板")

col1, col2, col3, col4 = st.columns(4)
col1.metric("MSTR 市價", f"${mstr_price:,.2f}")
col2.metric("BTC 現價", f"${btc_price:,.2f}")
col3.metric("去泡沫真實 mNAV", f"${real_nav_per_share:,.2f}")
col4.metric("真實溢價倍數", f"{nmav_premium:.2f}x")

# 警示邏輯
if nmav_premium < 1.0:
    st.error("🚨 進入嚴重折價區 (價值低估)")
elif nmav_premium > 2.0:
    st.warning("⚠️ 進入高溢價警報區")

st.info(f"最後更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
