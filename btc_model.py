import streamlit as st
import yfinance as yf
from datetime import datetime

# ==========================================
# 1. 核心參數配置區 (手動更新入口)
# ==========================================
st.sidebar.header("⚙️ MSTR 機構參數設置")
ADSO = st.sidebar.number_input("流通股數 (ADSO Millions)", value=386.052)
TOTAL_DEBT = st.sidebar.number_input("總負債 ($M)", value=6714)
TOTAL_PREF = st.sidebar.number_input("特別股 ($M)", value=15471)
CASH = st.sidebar.number_input("現金儲備 ($M)", value=1100)
MSTR_BTC = st.sidebar.number_input("BTC 總持倉", value=846842)
OFFICIAL_MNAV = st.sidebar.number_input("官方 mNAV 基準值", value=1.21)

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
# 3. 五大核心指標計算邏輯
# ==========================================
btc_market_val = (MSTR_BTC * btc) / 1_000_000

# 1. ADSO 去泡沫 mNAV：(市值 / BTC 持倉價值)
adso_nmav_premium = (ADSO * price) / btc_market_val

# 2. 企業價值 EV 溢價：(EV / BTC 持倉價值)
ev = (ADSO * price) + TOTAL_PREF + TOTAL_DEBT - CASH
ev_premium = ev / btc_market_val

# 3. 債務安全邊際：(淨資產 / BTC 市值)
debt_margin = (btc_market_val - TOTAL_DEBT) / btc_market_val

# 4. 每股含幣量 (BPS)：Sats per share
bps = MSTR_BTC / (ADSO * 1_000_000)

# 5. 價格乖離率：MSTR 股價對 BTC 價格的相對比率
price_deviation = price / btc

# ==========================================
# 4. 儀表板呈現
# ==========================================
st.set_page_config(layout="wide")
st.title("🛡️ MSTR 機構級去泡沫監控儀表板")

# 核心儀表
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("MSTR 現價", f"${price:.2f}")
c2.metric("ADSO 溢價", f"{adso_nmav_premium:.2f}x")
c3.metric("EV 溢價", f"{ev_premium:.2f}x")
c4.metric("乖離率", f"{price_deviation:.5f}")
c5.metric("每股含幣量", f"{bps*1e8:.0f} sats")

st.markdown("---")
st.subheader("📊 指標定義與風險判讀")

# 定義表格
data = {
    "指標": ["ADSO 去泡沫 mNAV", "企業價值 EV 溢價", "債務安全邊際", "每股含幣量", "價格乖離率"],
    "定義": [
        "基於流通股數與市值計算的直接溢價比", 
        "考慮負債與特別股後的總體企業併購溢價", 
        "BTC 市值扣除債務後的緩衝能力", 
        "每股股份實際擁有的比特幣硬實力 (Sats)", 
        "MSTR 股價相對於 BTC 價格的相對強弱"
    ],
    "警示標準": ["<1.0 折價, >2.0 高估", "<1.0 折價, >2.5 風險", "<0 違約風險臨界", "持續成長為佳", "觀察近期乖離變動率"]
}
st.table(pd.DataFrame(data))

# 警示訊息
if adso_nmav_premium > 2.0:
    st.warning("⚠️ 市場情緒過熱：ADSO 溢價已超過 2.0x，建議評估風險。")
elif adso_nmav_premium < 1.0:
    st.success("✅ 資產折價區：ADSO 溢價低於 1.0，具備價值投資安全邊際。")

st.info(f"最後更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
