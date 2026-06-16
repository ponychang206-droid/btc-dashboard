import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 側邊欄：參數校準區 ---
st.sidebar.header("⚙️ MSTR 核心指標校準")
ADSO = st.sidebar.number_input("流通股數 (ADSO Millions)", value=386.052)
MKT_VAL_DEBT = st.sidebar.number_input("債務市場價值 ($M)", value=7334)
MKT_VAL_PREF = st.sidebar.number_input("特別股市場價值 ($M)", value=21085)
CASH = st.sidebar.number_input("現金儲備 ($M)", value=1100)
MSTR_BTC = st.sidebar.number_input("BTC 總持倉", value=846842)

# --- 數據獲取 ---
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

# --- 計算核心引擎 ---
btc_mv = (MSTR_BTC * btc) / 1_000_000 # BTC 儲備市值 ($M)
market_cap_m = ADSO * price           # 當前股票市值 ($M)
ev = market_cap_m + MKT_VAL_DEBT + MKT_VAL_PREF - CASH # 企業併購價值 (EV)

# 指標計算
# 1. ADSO 去泡沫化溢價：市值相對於比特幣儲備的溢價
adso_premium = market_cap_m / btc_mv

# 2. EV 企業價值溢價：含債結構下的總價值相對於儲備溢價
ev_premium = ev / btc_mv

# 3. 債務安全邊際：比特幣儲備對債務的覆蓋率 (越高越安全)
debt_margin = (btc_mv - MKT_VAL_DEBT) / btc_mv

# 4. 每股含幣量 (Sats)：每一股實際持有的 BTC 單位
bps = MSTR_BTC / (ADSO * 1_000_000)

# 5. 價格乖離率：MSTR 股價對 BTC 現貨價格的相對強弱
price_dev = price / btc

# --- 儀表板呈現 ---
st.title("🛡️ MSTR 深度分析監控")

# 核心指標 metric
c1, c2, c3, c4 = st.columns(4)
c1.metric("ADSO 溢價", f"{adso_premium:.2f}x")
c2.metric("EV 溢價", f"{ev_premium:.2f}x")
c3.metric("債務安全邊際", f"{debt_margin:.1%}")
c4.metric("每股含幣量", f"{bps*1e8:.0f} sats")

st.markdown("---")
st.subheader("📊 指標定義表")

data = {
    "指標名稱": ["ADSO 溢價", "EV 溢價", "債務安全邊際", "每股含幣量", "價格乖離率"],
    "計算公式 (分子/分母)": ["市值 / BTC儲備", "企業價值 / BTC儲備", "(BTC儲備-債務) / BTC儲備", "總BTC / ADSO", "MSTR股價 / BTC價格"],
    "核心意義": ["市場對股份的直接溢價感受", "含槓桿結構後的併購估值溢價", "資產扣除債務後的緩衝能力", "投資人的持有硬實力", "市場情緒強弱與回歸參考"]
}
st.table(pd.DataFrame(data))

# 乖離率顯示
st.metric("當前乖離率 (Price Dev)", f"{price_dev:.5f}")

st.info(f"最後更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
