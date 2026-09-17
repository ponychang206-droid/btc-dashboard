import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ==========================================
# 0. 頁面設定
# ==========================================
st.set_page_config(
    page_title="MSTR 股價監控戰情室",
    layout="wide",
    initial_sidebar_state="expanded"
)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# ==========================================
# Session State 初始化
# ==========================================
DEFAULTS = {
    "MSTR_BTC_HOLDINGS":   845050,
    "MSTR_AVG_COST":       75412,
    "MSTR_BASIC_SHARES":   420497000,
    "MSTR_TOTAL_DEBT_M":   6714,
    "MSTR_TOTAL_PREF_M":   14481,
    "MSTR_CASH_RESERVE_M": 6398,
    "MSTR_FDSO":           424501000,
}
for k, v in DEFAULTS.items():
    if f"{k}_val" not in st.session_state:
        st.session_state[f"{k}_val"] = v

def save_params():
    for k in DEFAULTS.keys():
        if k in st.session_state:
            st.session_state[f"{k}_val"] = st.session_state[k]

# ── 備兌買權部位 Session State ──────────────────────────
CC_POSITIONS_DEFAULT = [
    {"id": 1, "label": "MSTR Sep25'26 $155", "strike": 155.0, "expiry": "2026-09-25", "contracts": 2,  "net_cash": 400.0,  "ticker": "MSTR", "active": True},
    {"id": 2, "label": "MSTR Nov20'26 $160", "strike": 160.0, "expiry": "2026-11-20", "contracts": 6,  "net_cash": 1600.0, "ticker": "MSTR", "active": True},
    {"id": 3, "label": "MSTR Dec18'26 $190", "strike": 190.0, "expiry": "2026-12-18", "contracts": 1,  "net_cash": 400.0,  "ticker": "MSTR", "active": True},
    {"id": 4, "label": "MSTR Dec18'26 $195", "strike": 195.0, "expiry": "2026-12-18", "contracts": 1,  "net_cash": 400.0,  "ticker": "MSTR", "active": True},
    {"id": 5, "label": "MSTR Jan15'27 $190", "strike": 190.0, "expiry": "2027-01-15", "contracts": 1,  "net_cash": 500.0,  "ticker": "MSTR", "active": True},
    {"id": 6, "label": "MSTR Jan15'27 $195", "strike": 195.0, "expiry": "2027-01-15", "contracts": 20, "net_cash": 4000.0, "ticker": "MSTR", "active": True},
    {"id": 7, "label": "COIN Nov20'26 $210", "strike": 210.0, "expiry": "2026-11-20", "contracts": 3,  "net_cash": 1084.0, "ticker": "COIN", "active": True},
]
if "cc_positions" not in st.session_state:
    st.session_state["cc_positions"] = CC_POSITIONS_DEFAULT

# ==========================================
# 1. 數據抓取模組
# ==========================================
@st.cache_data(ttl=30)
def fetch_btc_price():
    try:
        btc = yf.Ticker("BTC-USD")
        df = btc.history(period="2d", interval="5m")
        if not df.empty:
            price = float(df['Close'].iloc[-1])
            prev  = float(df['Close'].iloc[0])
            delta = (price - prev) / prev * 100
            return price, delta
        return 0, 0
    except:
        return 0, 0

@st.cache_data(ttl=60)
def fetch_mstr_data():
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="6mo", interval="1d")
        if hist.empty:
            return None
        price = float(hist['Close'].iloc[-1])
        delta = hist['Close'].diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = float((100 - 100 / (1 + rs)).iloc[-1])
        ma20 = float(hist['Close'].rolling(20).mean().iloc[-1])
        ma60 = float(hist['Close'].rolling(60).mean().iloc[-1]) if len(hist) >= 60 else ma20
        ma20_series = hist['Close'].rolling(20).mean()
        std20       = hist['Close'].rolling(20).std()
        bb_upper    = float((ma20_series + 2 * std20).iloc[-1])
        bb_lower    = float((ma20_series - 2 * std20).iloc[-1])
        log_ret = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
        hv30    = float(log_ret.tail(30).std() * np.sqrt(252)) if len(log_ret) >= 30 else 0
        return {
            'price': price, 'rsi': rsi,
            'ma20': ma20, 'ma60': ma60,
            'bb_upper': bb_upper, 'bb_lower': bb_lower,
            'hv30': hv30, 'hist': hist,
        }
    except:
        return None

@st.cache_data(ttl=60)
def fetch_mstr_options():
    try:
        mstr = yf.Ticker("MSTR")
        exps = mstr.options
        if not exps:
            return None, None, None
        chain     = mstr.option_chain(exps[0])
        calls     = chain.calls
        puts      = chain.puts
        pc_ratio  = float(puts['volume'].sum() / calls['volume'].sum()) if calls['volume'].sum() > 0 else 1.0

        mstr_data_inner = fetch_mstr_data()
        atm_iv = 0
        if mstr_data_inner:
            p = mstr_data_inner['price']
            hv30 = mstr_data_inner['hv30'] if mstr_data_inner['hv30'] > 0 else 0.85

            calls_v = calls[(calls['impliedVolatility'] > 0.50) &
                            (calls['impliedVolatility'] < 3.00)].copy()

            if not calls_v.empty:
                calls_v['dist'] = abs(calls_v['strike'] - p)
                near_atm = calls_v.sort_values('dist').head(5)
                atm_iv = float(near_atm['impliedVolatility'].median())
                if atm_iv < hv30 * 0.7:
                    atm_iv = hv30
            else:
                atm_iv = hv30

        return atm_iv, pc_ratio, exps[0]
    except:
        return 0, 1.0, None

@st.cache_data(ttl=60)
def fetch_beta_mstr_btc():
    try:
        mstr = yf.Ticker("MSTR").history(period="3mo", interval="1d")
        btc  = yf.Ticker("BTC-USD").history(period="3mo", interval="1d")
        mstr.index = mstr.index.tz_localize(None)
        btc.index  = btc.index.tz_localize(None)
        m_ret = mstr['Close'].pct_change().dropna()
        b_ret = btc['Close'].pct_change().dropna()
        combined = pd.concat([m_ret, b_ret], axis=1, join='inner').dropna()
        if len(combined) < 10:
            return 0
        cov = np.cov(combined.iloc[:, 0], combined.iloc[:, 1])[0][1]
        var = np.var(combined.iloc[:, 1])
        return cov / var if var != 0 else 0
    except:
        return 0

@st.cache_data(ttl=300)
def fetch_macro():
    try:
        tnx  = yf.Ticker("^TNX").history(period="5d")
        dxy  = yf.Ticker("DX-Y.NYB").history(period="5d")
        ndx  = yf.Ticker("^NDX").history(period="2d")
        t10y = float(tnx['Close'].iloc[-1]) if not tnx.empty else 0
        dxy_v= float(dxy['Close'].iloc[-1]) if not dxy.empty else 0
        ndx_d= 0
        if not ndx.empty and len(ndx) >= 2:
            ndx_d = (ndx['Close'].iloc[-1] - ndx['Close'].iloc[-2]) / ndx['Close'].iloc[-2] * 100
        return {'t10y': t10y, 'dxy': dxy_v, 'ndx_delta': ndx_d}
    except:
        return {'t10y': 0, 'dxy': 0, 'ndx_delta': 0}

@st.cache_data(ttl=30)
def fetch_funding_rate():
    try:
        url  = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
        data = requests.get(url, timeout=5).json()
        return float(data.get("lastFundingRate", 0.0001))
    except:
        return 0.0001

@st.cache_data(ttl=300)
def fetch_fear_greed():
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8).json()
        return int(data["data"][0]["value"])
    except:
        return 50

@st.cache_data(ttl=30)
def fetch_200wma():
    try:
        df = yf.Ticker("BTC-USD").history(period="max", interval="1wk")
        if not df.empty:
            df = df.reset_index()
            df['200WMA'] = df['Close'].rolling(200).mean()
            return float(df['200WMA'].iloc[-1])
        return 0
    except:
        return 0

# ==========================================
# 2. 側邊欄
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ MSTR 財務參數")
    st.caption("修改後自動儲存，刷新保留")

    MSTR_BTC_HOLDINGS = st.number_input("BTC 總持倉量",
        value=st.session_state["MSTR_BTC_HOLDINGS_val"], step=100,
        key="MSTR_BTC_HOLDINGS", on_change=save_params)
    MSTR_AVG_COST = st.number_input("平均買入成本 ($/BTC)",
        value=st.session_state["MSTR_AVG_COST_val"], step=100,
        key="MSTR_AVG_COST", on_change=save_params)

    st.markdown("---")
    st.markdown("**官方 mNAV 參數**")
    st.caption("mNAV = 股價 ÷ Net BPS（官方定義）")
    MSTR_BASIC_SHARES = st.number_input("基本流通股數 (Basic)",
        value=st.session_state["MSTR_BASIC_SHARES_val"], step=1000000,
        key="MSTR_BASIC_SHARES", on_change=save_params)
    MSTR_TOTAL_DEBT_M = st.number_input("總債務 Total Debt (百萬$)",
        value=st.session_state["MSTR_TOTAL_DEBT_M_val"], step=100,
        key="MSTR_TOTAL_DEBT_M", on_change=save_params)
    MSTR_TOTAL_PREF_M = st.number_input("優先股 Total Pref (百萬$)",
        value=st.session_state["MSTR_TOTAL_PREF_M_val"], step=100,
        key="MSTR_TOTAL_PREF_M", on_change=save_params)
    MSTR_CASH_RESERVE_M = st.number_input("現金儲備 USD Cash (百萬$)",
        value=st.session_state["MSTR_CASH_RESERVE_M_val"], step=100,
        key="MSTR_CASH_RESERVE_M", on_change=save_params)

    st.markdown("---")
    st.markdown("**CEBE mNAV 參數**")
    st.caption("用 FDSO（價內稀釋股數）最貼近官方")
    MSTR_FDSO = st.number_input("完全稀釋股數 FDSO",
        value=st.session_state["MSTR_FDSO_val"], step=1000000,
        key="MSTR_FDSO", on_change=save_params)

    st.markdown("---")

    btc_price, btc_delta = fetch_btc_price()
    mstr_data  = fetch_mstr_data()
    mstr_price = mstr_data['price'] if mstr_data else 0
    funding    = fetch_funding_rate()
    fng        = fetch_fear_greed()
    macro      = fetch_macro()
    ma200w     = fetch_200wma()
    beta_btc   = fetch_beta_mstr_btc()
    atm_iv, pc_ratio, next_exp = fetch_mstr_options()

    if btc_price > 0 and mstr_price > 0:
        # ── 官方 mNAV 計算（完全對齊 MSTR 官方定義）────────
        # 公式：mNAV = 股價 ÷ Net BPS (USD)
        # Net BTC = BTC 持倉 − 債務 − 優先股 + USD Assets
        usd_assets_m        = MSTR_CASH_RESERVE_M
        net_btc             = MSTR_BTC_HOLDINGS - (MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - usd_assets_m) * 1e6 / btc_price
        net_bps_usd         = (net_btc / MSTR_FDSO) * btc_price if MSTR_FDSO > 0 else 0
        official_mnav       = mstr_price / net_bps_usd if net_bps_usd > 0 else 0

        # 輔助顯示用
        btc_reserve_m       = btc_price * MSTR_BTC_HOLDINGS / 1e6
        net_reserve_m       = btc_reserve_m + usd_assets_m - MSTR_TOTAL_DEBT_M - MSTR_TOTAL_PREF_M

        # ── CEBE mNAV 計算（保持不變）────────────────────
        net_claims_m        = MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - MSTR_CASH_RESERVE_M
        claims_btc          = net_claims_m * 1e6 / btc_price
        common_equity_btc   = MSTR_BTC_HOLDINGS - claims_btc
        cebe_sats           = int(common_equity_btc / MSTR_FDSO * 1e8) if MSTR_FDSO > 0 else 0
        drag_pct            = claims_btc / MSTR_BTC_HOLDINGS * 100
        cebe_per_share      = cebe_sats / 1e8 * btc_price
        cebe_mnav           = mstr_price / cebe_per_share if cebe_per_share > 0 else 0
    else:
        official_mnav = cebe_mnav = cebe_sats = drag_pct = cebe_per_share = 0
        btc_reserve_m = net_reserve_m = net_btc = net_bps_usd = 0
        net_claims_m = claims_btc = common_equity_btc = 0

    if btc_price > 0:
        pnl_usd   = (btc_price - MSTR_AVG_COST) * MSTR_BTC_HOLDINGS
        pnl_color = "green" if pnl_usd >= 0 else "red"
        st.markdown(f"💼 BTC持倉損益：<span style='color:{pnl_color};font-weight:bold;'>${pnl_usd/1e9:.2f}B</span>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📈 即時 mNAV")
    oc = "#f3ba2f" if official_mnav >= 1 else "#0ecb81"
    cc = "#f3ba2f" if cebe_mnav >= 1 else "#0ecb81"
    st.markdown(f"""
        <div style="background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:10px;color:#848e9c;">🏛️ 官方 mNAV（官方定義）</div>
            <div style="font-size:24px;font-weight:800;color:{oc};font-family:monospace;">{official_mnav:.3f}x</div>
            <div style="font-size:10px;color:#848e9c;">股價 ${mstr_price:.2f} ÷ Net BPS ${net_bps_usd:.2f}</div>
        </div>
        <div style="background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:12px;margin-bottom:8px;">
            <div style="font-size:10px;color:#848e9c;">🔬 CEBE mNAV（普通股真實溢價）</div>
            <div style="font-size:24px;font-weight:800;color:{cc};font-family:monospace;">{cebe_mnav:.3f}x</div>
            <div style="font-size:10px;color:#848e9c;">股價 ${mstr_price:.2f} ÷ CEBE ${cebe_per_share:.2f}（{cebe_sats:,} sats）</div>
            <div style="font-size:10px;color:#f6465d;">Drag = {drag_pct:.1f}%</div>
        </div>
    """, unsafe_allow_html=True)

    with st.expander("💡 什麼是 CEBE？"):
        st.markdown(f"""
**CEBE = Claim-Encumbered Bitcoin Equivalent**
被債權人索償權壓著的比特幣等值。

**官方計算步驟：**
1. 淨索償額 = Debt + Pref - Cash = **${net_claims_m/1000:.2f}B**
2. 換算成 BTC = **{claims_btc:,.0f} BTC**
3. 普通股BTC = {MSTR_BTC_HOLDINGS:,} - {claims_btc:,.0f} = **{common_equity_btc:,.0f} BTC**
4. 每股CEBE = **{cebe_sats:,} sats**
5. Drag = {claims_btc:,.0f} / {MSTR_BTC_HOLDINGS:,} = **{drag_pct:.1f}%**

CEBE mNAV > 1 → 發新股對股東仍有利
CEBE mNAV < 1 → 繼續發股會稀釋股東
""")

# ==========================================
# 3. 主頁面
# ==========================================
st.markdown(f"""
<div style="padding:10px 0 20px 0;border-bottom:1px solid #2b3139;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:700;color:#eaecef;">
        📡 MSTR 股價監控戰情室
    </div>
    <div style="font-size:12px;color:#848e9c;margin-top:4px;">
        更新時間：{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')} 台北時間
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0b0e11 !important;
    color: #eaecef !important;
    font-family: 'SF Pro Display', -apple-system, sans-serif;
}
[data-testid="stHeader"] { background: rgba(0,0,0,0); }
[data-testid="stSidebar"] { background-color: #161b22 !important; }
footer { visibility: hidden; }
.kpi { background:#161b22; border:1px solid #2b3139; border-radius:8px; padding:14px 16px; margin-bottom:8px; }
.kpi-label { font-size:10px; color:#848e9c; text-transform:uppercase; letter-spacing:1px; margin-bottom:4px; }
.kpi-value { font-size:20px; font-weight:700; font-family:monospace; }
.kpi-sub   { font-size:10px; color:#848e9c; margin-top:3px; }
.sig-bull  { background:#0d2818; border-left:4px solid #238636; border-radius:6px; padding:12px 14px; margin-bottom:8px; }
.sig-bear  { background:#2d1517; border-left:4px solid #da3633; border-radius:6px; padding:12px 14px; margin-bottom:8px; }
.sig-neut  { background:#1c1f26; border-left:4px solid #6e7681; border-radius:6px; padding:12px 14px; margin-bottom:8px; }
.sig-t { font-size:12px; font-weight:700; margin-bottom:4px; }
.sig-d { font-size:11px; color:#8b949e; line-height:1.5; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. KPI 列
# ==========================================
st.markdown("#### 📊 核心即時指標")
k1,k2,k3,k4,k5,k6 = st.columns(6)

def kpi(col, label, value, sub="", color="#eaecef"):
    col.markdown(f"""<div class="kpi">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value" style="color:{color};">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)

mstr_chg_color = "#238636" if mstr_price >= (mstr_data['ma20'] if mstr_data else 0) else "#da3633"
btc_chg_color  = "#238636" if btc_delta >= 0 else "#da3633"
rsi_color = "#da3633" if mstr_data and mstr_data['rsi'] > 70 else "#238636" if mstr_data and mstr_data['rsi'] < 30 else "#f0883e"
iv_color  = "#f0883e" if atm_iv > 0 else "#848e9c"
fng_color = "#238636" if fng <= 30 else "#da3633" if fng >= 70 else "#848e9c"

kpi(k1, "MSTR 股價", f"${mstr_price:.2f}",
    f"MA20 ${mstr_data['ma20']:.2f} | MA60 ${mstr_data['ma60']:.2f}" if mstr_data else "",
    mstr_chg_color)
kpi(k2, "BTC 即時價格", f"${btc_price:,.0f}",
    f"24H {btc_delta:+.2f}%", btc_chg_color)
kpi(k3, "RSI (14)", f"{mstr_data['rsi']:.1f}" if mstr_data else "N/A",
    "超買 >70 | 超賣 <30", rsi_color)
kpi(k4, "隱含波動率 IV", f"{atm_iv*100:.1f}%" if atm_iv > 0 else "N/A",
    f"HV30 {mstr_data['hv30']*100:.1f}% | IV/HV {atm_iv/mstr_data['hv30']:.2f}x" if mstr_data and mstr_data['hv30'] > 0 and atm_iv > 0 else "",
    iv_color)
kpi(k5, "Put/Call Ratio", f"{pc_ratio:.2f}" if pc_ratio else "N/A",
    ">1.0 市場偏空 | <0.7 市場偏多",
    "#da3633" if pc_ratio and pc_ratio > 1.0 else "#238636" if pc_ratio and pc_ratio < 0.7 else "#848e9c")
kpi(k6, "恐懼貪婪指數", f"{fng}/100",
    "😱極恐" if fng<=25 else "😟恐懼" if fng<=45 else "😐中性" if fng<=55 else "😏貪婪" if fng<=75 else "🤑極貪",
    fng_color)

k7,k8,k9,k10,k11,k12 = st.columns(6)
kpi(k7, "MSTR/BTC Beta", f"{beta_btc:.2f}x",
    f"BTC漲1%→MSTR預期{beta_btc:.2f}%", "#a5d6ff")
kpi(k8, "BTC 資金費率", f"{funding*100:+.4f}%",
    "空頭過熱" if funding < -0.0002 else "多空平衡" if abs(funding) < 0.0002 else "多頭過熱",
    "#238636" if funding < -0.0002 else "#da3633" if funding > 0.0005 else "#848e9c")
kpi(k9, "美債10年殖利率", f"{macro['t10y']:.2f}%",
    "高→估值壓縮" if macro['t10y'] > 4.5 else "低→估值擴張",
    "#da3633" if macro['t10y'] > 4.5 else "#238636")
kpi(k10, "美元指數 DXY", f"{macro['dxy']:.2f}",
    "強→BTC承壓" if macro['dxy'] > 103 else "弱→BTC助漲",
    "#da3633" if macro['dxy'] > 103 else "#238636")
kpi(k11, "納斯達克 NDX", f"{macro['ndx_delta']:+.2f}%",
    "科技股情緒參考",
    "#238636" if macro['ndx_delta'] >= 0 else "#da3633")

dist_200w = (btc_price - ma200w) / ma200w * 100 if ma200w > 0 else 0
kpi(k12, "BTC 200週均線", f"${ma200w:,.0f}",
    f"現價距離 {dist_200w:+.1f}%",
    "#da3633" if dist_200w < 10 else "#238636")

# ==========================================
# 5. 圖表區
# ==========================================
st.markdown("---")
col_chart, col_sig = st.columns([1.6, 1])

with col_chart:
    st.markdown("#### 📈 MSTR 6個月股價走勢")
    if mstr_data and not mstr_data['hist'].empty:
        h = mstr_data['hist'].copy()
        h['MA20'] = h['Close'].rolling(20).mean()
        h['MA60'] = h['Close'].rolling(60).mean()
        h['BB_U'] = h['Close'].rolling(20).mean() + 2*h['Close'].rolling(20).std()
        h['BB_L'] = h['Close'].rolling(20).mean() - 2*h['Close'].rolling(20).std()

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=h.index, open=h['Open'], high=h['High'], low=h['Low'], close=h['Close'],
            name='MSTR', increasing_line_color='#238636', decreasing_line_color='#da3633'
        ))
        fig.add_trace(go.Scatter(x=h.index, y=h['MA20'], name='MA20', line=dict(color='#f0883e', width=1.2)))
        fig.add_trace(go.Scatter(x=h.index, y=h['MA60'], name='MA60', line=dict(color='#a5d6ff', width=1.2, dash='dash')))
        fig.add_trace(go.Scatter(x=h.index, y=h['BB_U'], name='BB上軌', line=dict(color='#6e7681', width=0.8, dash='dot')))
        fig.add_trace(go.Scatter(x=h.index, y=h['BB_L'], name='BB下軌', line=dict(color='#6e7681', width=0.8, dash='dot'), fill='tonexty', fillcolor='rgba(110,118,129,0.05)'))
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, tickfont=dict(color='#848e9c'), rangeslider_visible=False),
            yaxis=dict(showgrid=True, gridcolor='#21262d', tickfont=dict(color='#848e9c')),
            legend=dict(font=dict(color='#848e9c', size=10), orientation='h', y=1.05),
            height=380, margin=dict(l=0,r=0,t=30,b=0)
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

with col_sig:
    st.markdown("#### 🚦 多維訊號判讀")
    if mstr_data:
        rsi_val = mstr_data['rsi']
        if rsi_val > 70:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 RSI 超買（{rsi_val:.1f}）</div><div class="sig-d">短期漲幅過大，注意回調風險，備兌買權履約價可設近一點。</div></div>', unsafe_allow_html=True)
        elif rsi_val < 30:
            st.markdown(f'<div class="sig-bull"><div class="sig-t" style="color:#238636;">🟢 RSI 超賣（{rsi_val:.1f}）</div><div class="sig-d">短期跌幅過大，反彈機率上升，可考慮逢低布局。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ RSI 中性（{rsi_val:.1f}）</div><div class="sig-d">動能正常，無超買超賣訊號。</div></div>', unsafe_allow_html=True)

    if mstr_data:
        if mstr_price >= mstr_data['bb_upper']:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 觸及布林上軌（${mstr_data["bb_upper"]:.2f}）</div><div class="sig-d">股價觸及統計超買區，短期回調機率高，賣備兌買權時機佳。</div></div>', unsafe_allow_html=True)
        elif mstr_price <= mstr_data['bb_lower']:
            st.markdown(f'<div class="sig-bull"><div class="sig-t" style="color:#238636;">🟢 觸及布林下軌（${mstr_data["bb_lower"]:.2f}）</div><div class="sig-d">股價觸及統計超賣區，反彈機率高。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ 布林通道：正常區間</div><div class="sig-d">上軌 ${mstr_data["bb_upper"]:.2f} | 下軌 ${mstr_data["bb_lower"]:.2f}</div></div>', unsafe_allow_html=True)

    if atm_iv > 0 and mstr_data and mstr_data['hv30'] > 0:
        iv_hv = atm_iv / mstr_data['hv30']
        if iv_hv > 1.15:
            st.markdown(f'<div class="sig-bull"><div class="sig-t" style="color:#238636;">🟢 IV > HV（{iv_hv:.2f}x）賣權利金時機佳</div><div class="sig-d">隱含波動率溢價明顯，賣出備兌買權收取的權利金高於統計公平值。</div></div>', unsafe_allow_html=True)
        elif iv_hv < 0.9:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 IV < HV（{iv_hv:.2f}x）賣出性價比差</div><div class="sig-d">權利金被低估，此時賣備兌買權不划算。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ IV/HV 中性（{iv_hv:.2f}x）</div><div class="sig-d">選擇權定價正常。</div></div>', unsafe_allow_html=True)

    if pc_ratio:
        if pc_ratio > 1.0:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 P/C Ratio 偏高（{pc_ratio:.2f}）</div><div class="sig-d">市場偏空情緒濃厚，但極端高值往往是反向指標。</div></div>', unsafe_allow_html=True)
        elif pc_ratio < 0.6:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 P/C Ratio 過低（{pc_ratio:.2f}）</div><div class="sig-d">市場過度樂觀，Call 買盤擁擠，注意回調風險。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ P/C Ratio 中性（{pc_ratio:.2f}）</div><div class="sig-d">多空情緒平衡。</div></div>', unsafe_allow_html=True)

    if cebe_mnav > 0:
        if cebe_mnav > 1.5:
            st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 CEBE mNAV 偏高（{cebe_mnav:.3f}x）</div><div class="sig-d">股價溢價過高，泡沫風險上升，備兌買權履約價可積極設近。</div></div>', unsafe_allow_html=True)
        elif cebe_mnav < 1.05:
            st.markdown(f'<div class="sig-bull"><div class="sig-t" style="color:#238636;">🟢 CEBE mNAV 接近清算價值（{cebe_mnav:.3f}x）</div><div class="sig-d">股價接近每股真實BTC淨值，市場定價清算風險，歷史上為優質買點。</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sig-neut"><div class="sig-t" style="color:#8b949e;">⚪ CEBE mNAV 正常（{cebe_mnav:.3f}x）</div><div class="sig-d">溢價在合理區間，持續監控。</div></div>', unsafe_allow_html=True)

    if macro['t10y'] > 4.5:
        st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 美債殖利率偏高（{macro["t10y"]:.2f}%）</div><div class="sig-d">高利率環境壓縮成長股估值，MSTR 溢價可能收縮。</div></div>', unsafe_allow_html=True)
    if macro['dxy'] > 103:
        st.markdown(f'<div class="sig-bear"><div class="sig-t" style="color:#da3633;">🔴 美元偏強（DXY {macro["dxy"]:.2f}）</div><div class="sig-d">強勢美元對 BTC 形成壓力，連帶影響 MSTR。</div></div>', unsafe_allow_html=True)

# ==========================================
# 7. 選擇權鏈
# ==========================================
st.markdown("---")
st.markdown("#### 📋 MSTR 選擇權鏈（ATM 附近，最近到期）")
try:
    mstr_obj = yf.Ticker("MSTR")
    exps = mstr_obj.options
    if exps and mstr_price > 0:
        exp_choice = st.selectbox("選擇到期日", exps[:6], index=0)
        chain = mstr_obj.option_chain(exp_choice)
        calls = chain.calls.copy()
        puts  = chain.puts.copy()
        calls['dist'] = abs(calls['strike'] - mstr_price)

        atm_calls = calls.sort_values('dist').head(10).sort_values('strike').reset_index(drop=True)

        atm_calls['ATM'] = atm_calls['strike'].apply(
            lambda x: '← ATM' if abs(x - mstr_price) == atm_calls['dist'].min() else '')

        iv_fallback = mstr_data['hv30'] if mstr_data and mstr_data['hv30'] > 0 else 0.8
        atm_calls['IV顯示'] = atm_calls['impliedVolatility'].apply(
            lambda x: f"{x*100:.1f}%" if x > 0 else f"~{iv_fallback*100:.1f}%(HV)")

        disp = atm_calls[['strike','lastPrice','bid','ask','IV顯示','volume','openInterest','ATM']].copy()
        disp.columns = ['履約價','最新成交','Bid','Ask','IV','成交量','未平倉量','']
        disp['履約價'] = disp['履約價'].apply(lambda x: f"${x:.0f}")
        disp['最新成交'] = disp['最新成交'].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
        disp['Bid'] = disp['Bid'].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
        disp['Ask'] = disp['Ask'].apply(lambda x: f"${x:.2f}" if x > 0 else "—")
        disp['成交量'] = disp['成交量'].apply(lambda x: f"{int(x):,}" if x > 0 else "—")
        disp['未平倉量'] = disp['未平倉量'].apply(lambda x: f"{int(x):,}" if x > 0 else "—")

        st.caption(f"到期日：{exp_choice} | MSTR 現價 ${mstr_price:.2f} | Call 選擇權 | Bid/Ask 為 '—' 表示盤後無報價，下個交易日開盤後更新")
        st.dataframe(disp.reset_index(drop=True), use_container_width=True, hide_index=True)

        pc_vol = puts['volume'].sum() / calls['volume'].sum() if calls['volume'].sum() > 0 else 0
        st.caption(f"📊 P/C 成交量比：{pc_vol:.2f} | Put 總量：{int(puts['volume'].sum()):,} | Call 總量：{int(calls['volume'].sum()):,}")
except Exception as e:
    st.warning(f"選擇權鏈載入失敗：{e}")

# ==========================================
# 7b. 備兌買權部位監控與策略建議
# ==========================================
import math
from scipy.stats import norm as scipy_norm

def bs_call(S, K, T, r, sigma):
    """Black-Scholes Call 定價"""
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(S - K, 0), 0, 0, 0
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    price    = S*scipy_norm.cdf(d1) - K*math.exp(-r*T)*scipy_norm.cdf(d2)
    delta    = scipy_norm.cdf(d1)
    theta    = (-(S*scipy_norm.pdf(d1)*sigma)/(2*math.sqrt(T)) - r*K*math.exp(-r*T)*scipy_norm.cdf(d2)) / 365
    prob_itm = scipy_norm.cdf(d2)
    return price, delta, theta, prob_itm

st.markdown("---")
st.markdown("## 🎯 備兌買權部位監控與平倉策略")

# 編輯模式
with st.expander("✏️ 編輯部位（新增/修改/停用）"):
    st.caption("⚠️ net_cash = 這筆合約從開倉至今的歷史淨收入總額（正=淨收，負=淨付）。請根據券商實際數據手動修正。")
    positions = st.session_state["cc_positions"]
    for i, pos in enumerate(positions):
        c1,c2,c3,c4,c5,c6 = st.columns([2,1.2,1.5,1,1.2,0.8])
        positions[i]["label"]     = c1.text_input("名稱", pos["label"],     key=f"cc_label_{i}")
        positions[i]["strike"]    = c2.number_input("履約價$", pos["strike"], step=5.0, key=f"cc_k_{i}")
        positions[i]["expiry"]    = c3.text_input("到期(YYYY-MM-DD)", pos["expiry"], key=f"cc_exp_{i}")
        positions[i]["contracts"] = c4.number_input("口數", pos["contracts"], step=1, key=f"cc_ct_{i}")
        positions[i]["net_cash"]  = c5.number_input("歷史淨收入$", pos["net_cash"], step=10.0, key=f"cc_cash_{i}")
        positions[i]["active"]    = c6.checkbox("啟用", pos["active"], key=f"cc_act_{i}")
    if st.button("➕ 新增部位"):
        st.session_state["cc_positions"].append({
            "id": len(positions)+1, "label": "新部位",
            "strike": 200.0, "expiry": "2025-12-19",
            "contracts": 1, "net_cash": 0.0, "ticker": "MSTR", "active": True
        })
        st.rerun()
    st.session_state["cc_positions"] = positions

# 計算並顯示所有部位
r_rf = 0.045
positions = [p for p in st.session_state["cc_positions"] if p["active"]]

if mstr_price > 0 and positions:
    now = datetime.now(TAIPEI_TZ)
    rows_cc = []
    urgent_positions = []

    for pos in positions:
        try:
            exp_dt = datetime.strptime(pos["expiry"], "%Y-%m-%d")
            today  = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            days_left = max(0, (exp_dt - today).days)
            T = max(days_left, 1) / 365
        except:
            days_left = 30
            T = 30/365

        iv_use = atm_iv if atm_iv > 0 else (mstr_data['hv30'] if mstr_data and mstr_data['hv30'] > 0 else 0.85)
        if iv_use <= 0:
            iv_use = 0.85

        iv_valid = iv_use >= 0.50

        if iv_valid:
            bs_price, delta, theta, prob_itm = bs_call(mstr_price, pos["strike"], T, r_rf, iv_use)
            bs_disp    = f"${bs_price:.2f}"
            delta_disp = f"{delta:.2f}"
            prob_disp  = f"{prob_itm*100:.1f}%"
            theta_disp = f"${theta:.3f}"
        else:
            bs_price = delta = theta = prob_itm = 0
            bs_disp    = "—"
            delta_disp = "—"
            prob_disp  = "—"
            theta_disp = "—"

        net_cash    = pos["net_cash"]
        buyback_est = bs_price * 100 * pos["contracts"] if iv_valid else 0
        total_pnl   = net_cash - buyback_est
        pnl_per     = total_pnl / pos["contracts"] if pos["contracts"] > 0 else 0

        if iv_valid:
            if prob_itm > 0.7 or days_left <= 14:
                urgency = "🔴 緊急"
                urgent_positions.append(pos)
            elif prob_itm > 0.4 or days_left <= 30:
                urgency = "🟡 注意"
            else:
                urgency = "🟢 安全"
        else:
            urgency = "⚠️ IV異常"

        rows_cc.append({
            "部位":       pos["label"],
            "履約價":     f"${pos['strike']:.0f}",
            "到期":       pos["expiry"],
            "剩餘天數":   f"{days_left}天",
            "口數":       pos["contracts"],
            "B-S估價":    bs_disp,
            "Delta":      delta_disp,
            "被指派機率": prob_disp,
            "Theta/天":   theta_disp,
            "每口P&L":    f"${pnl_per:+.0f}",
            "總P&L":      f"${total_pnl:+,.0f}",
            "狀態":       urgency,
        })

    df_cc = pd.DataFrame(rows_cc)
    st.dataframe(df_cc, use_container_width=True, hide_index=True)

    # 總覽
    if atm_iv >= 0.50:
        total_buyback = sum(
            bs_call(mstr_price, p["strike"],
                    max(1,(datetime.strptime(p["expiry"],"%Y-%m-%d")-datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)).days)/365,
                    r_rf, atm_iv)[0] * 100 * p["contracts"]
            for p in positions
        )
    else:
        total_buyback = 0

    total_net_cash = sum(p["net_cash"] for p in positions)
    net_pnl_all = total_net_cash - total_buyback if total_buyback > 0 else 0

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("全部平倉估算成本", f"${total_buyback:,.0f}" if total_buyback > 0 else "—")
    col_b.metric("這批合約歷史淨收入", f"${total_net_cash:,.0f}")
    col_c.metric("淨損益（正=獲利）", f"${net_pnl_all:+,.0f}" if total_buyback > 0 else "—",
                 delta="獲利" if net_pnl_all >= 0 else "虧損" if total_buyback > 0 else "")

    if atm_iv < 0.50:
        st.warning("⚠️ 當前 IV 數據異常（< 50%），B-S 估價與損益計算暫停。請等待下個交易日開盤後，或手動檢查 IV 來源。")

    # ==========================================
    # 期權指標解釋定義
    # ==========================================
    with st.expander("📖 期權指標解釋：B-S估價、Delta、Theta/天"):
        st.markdown(f"""
### 📌 B-S估價（Black-Scholes 估價）
**定義**：用 Black-Scholes 選擇權定價模型計算出來的**理論合理價格**。

**對賣方的意義**：這代表**你現在如果要買回這口合約，大概要花多少錢**。

**如何解讀**：
- B-S 估價 **遠低於**你當初賣出的價格 → 你處於獲利狀態。
- B-S 估價 **接近或高於**你當初賣出的價格 → 你處於虧損狀態，或即將被指派。
- 這是理論價，實際買回價格要看市場的 Bid/Ask。

---

### 📌 Delta
**定義**：選擇權價格對「股價變動」的敏感度。範圍在 0 ~ 1 之間（Call）。

**對賣方的意義**：代表**「股價每上漲 1 美元，這口合約的理論價格會上漲多少美元」**。

**如何解讀**：
- **Delta = 0.2**：股價漲 1 元，合約漲 0.2 元。股價離履約價還很遠，**相對安全**。
- **Delta = 0.8**：股價漲 1 元，合約漲 0.8 元。股價已接近或超過履約價，**被指派的風險極高**。
- Delta 也可以粗略視為「被指派的機率」。

---

### 📌 Theta/天
**定義**：選擇權價格對「時間流逝」的敏感度。代表**「每過一天，這口合約的理論價格會衰減多少錢」**。

**對賣方的意義**：因為你是**賣方**，時間衰減對你**有利**。這代表你每天躺著不動，就能賺到的錢（假設股價不變）。

**如何解讀**：
- Theta 絕對值越大，代表時間價值流逝越快，對賣方越有利。
- 通常越接近到期日，Theta 的衰減會越劇烈（加速度衰減）。
- 如果 Theta 很小（例如 -0.01），代表這口合約已經沒什麼時間價值可賺了，可以考慮平倉換新的合約。

---

### 📌 被指派機率
**定義**：根據 B-S 模型中的 `d2` 參數計算出來的**「到期時，股價高於履約價的機率」**。

**對賣方的意義**：這是**你最需要關注的風險指標**。如果這個機率很高，代表時間價值所剩無幾，你很有可能在到期時被要求用履約價賣出股票。

**如何解讀**：
- **< 30%**：🟢 安全。時間對你有利，可以繼續放著收 Theta。
- **30% ~ 60%**：🟡 注意。股價開始靠近履約價，需開始考慮 Roll 倉。
- **> 60%**：🔴 緊急。大概率會被指派，必須立刻決定要平倉、Roll 倉，還是接受被拿走股票。
""")

    # 策略建議
    st.markdown("### 💡 策略建議")

    for pos in positions:
        try:
            exp_dt = datetime.strptime(pos["expiry"], "%Y-%m-%d")
            today  = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            days_left = max(0, (exp_dt - today).days)
            T = max(days_left, 1) / 365
        except:
            days_left, T = 30, 30/365

        iv_use = atm_iv if atm_iv > 0 else (mstr_data["hv30"] if mstr_data and mstr_data["hv30"] > 0 else 0.85)
        if iv_use <= 0: iv_use = 0.85

        if iv_use >= 0.50:
            bs_price, delta, theta, prob_itm = bs_call(mstr_price, pos["strike"], T, r_rf, iv_use)
            buyback_est = bs_price * 100 * pos["contracts"]
            total_pnl   = pos["net_cash"] - buyback_est

            if days_left <= 21 or prob_itm > 0.6:
                st.markdown(f"""
<div style="background:#2d1517;border-left:4px solid #da3633;border-radius:6px;padding:14px;margin-bottom:10px;">
<div style="font-size:13px;font-weight:700;color:#da3633;">🚨 【立即處理】{pos["label"]} — 剩 {days_left} 天，被指派機率 {prob_itm*100:.1f}%</div>
<div style="font-size:12px;color:#c9d1d9;margin-top:8px;line-height:1.7;">
<b>選項 A：立即買回平倉</b><br>
估算買回成本：${bs_price:.2f}/股 × 100 × {pos["contracts"]}口 = <b>${buyback_est:,.0f}</b><br>
這筆歷史淨收入：${pos["net_cash"]:,.0f} → 總損益 <b>${total_pnl:+,.0f}</b><br><br>
<b>選項 B：Roll Forward（向後延期）</b><br>
買回此部位，同時賣出更遠到期日的相同或更高履約價Call，收取時間價值差額，避免股票被拿走。<br><br>
<b>選項 C：Roll Up & Out（向上+向後）</b><br>
若股價已超過履約價，買回後賣出更高履約價+更遠到期的Call，以時間換空間，保留更多上漲空間。
</div>
</div>""", unsafe_allow_html=True)

            elif prob_itm > 0.35:
                st.markdown(f"""
<div style="background:#1c1f26;border-left:4px solid #f0883e;border-radius:6px;padding:14px;margin-bottom:10px;">
<div style="font-size:13px;font-weight:700;color:#f0883e;">⚠️ 【持續監控】{pos["label"]} — 被指派機率 {prob_itm*100:.1f}%，剩 {days_left} 天</div>
<div style="font-size:12px;color:#c9d1d9;margin-top:8px;line-height:1.7;">
當前 B-S 估價 ${bs_price:.2f}，Theta 每天衰減 ${abs(theta):.3f}（對賣方有利）。<br>
建議：若股價持續上漲接近 ${pos["strike"]:.0f}，提前評估 Roll Up & Out；若股價回落，等待 Theta 侵蝕後再決策。
</div>
</div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
<div style="background:#0d2818;border-left:4px solid #238636;border-radius:6px;padding:14px;margin-bottom:10px;">
<div style="font-size:13px;font-weight:700;color:#238636;">✅ 【安全觀察】{pos["label"]} — 被指派機率 {prob_itm*100:.1f}%，剩 {days_left} 天</div>
<div style="font-size:12px;color:#c9d1d9;margin-top:8px;">
Theta 每天衰減 ${abs(theta):.3f}，時間對賣方有利。繼續持有，每日損益：+${abs(theta)*100*pos["contracts"]:.0f}（{pos["contracts"]}口Theta收益）。
</div>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
<div style="background:#1c1f26;border-left:4px solid #6e7681;border-radius:6px;padding:14px;margin-bottom:10px;">
<div style="font-size:13px;font-weight:700;color:#8b949e;">⚠️ 【IV 數據異常】{pos["label"]} — 暫停風險評估</div>
<div style="font-size:12px;color:#c9d1d9;margin-top:8px;">
當前抓到的 IV 過低（< 50%），無法進行可靠的 B-S 計算。請等待下個交易日開盤後刷新頁面。
</div>
</div>""", unsafe_allow_html=True)

    # Roll 策略說明
    with st.expander("📖 Roll 策略詳細說明"):
        st.markdown(f"""
**當前 MSTR 股價：${mstr_price:.2f} | IV：{atm_iv*100:.1f}% | 下一到期日：{next_exp}**

---
### Roll Forward（向後展期）
- **適用時機**：股價接近或超過履約價，但你仍看好後市，不想被指派
- **操作**：買回當前到期的Call，同時賣出相同履約價但更遠到期的Call
- **淨收支**：通常需要支付少量差額（時間價值較遠的較貴）
- **效果**：爭取更多時間，讓股價可能回落至履約價下方

### Roll Up & Out（向上且向後展期）
- **適用時機**：股價已明顯超過履約價，繼續持有原Call必定被指派
- **操作**：買回當前Call，賣出更高履約價+更遠到期的Call
- **淨收支**：通常需要支付較大差額（換更高履約價需要付出溢價）
- **效果**：保留持股，同時鎖定更高的潛在賣出價格

### 直接平倉（Buy to Close）
- **適用時機**：已獲利50%以上，或距到期剩不到2週且深度價內
- **黃金法則**：當買回成本 ≤ 原始收取權利金的50%時，提前平倉鎖利並重新賣出新的Call
- **效果**：釋放資本效率，減少尾端風險
""")

# ==========================================
# 8. CEBE 壓力測試模擬表（40k~200k，每1萬一級）
# ==========================================
st.markdown("---")
st.subheader("📊 MSTR CEBE 股價真實價值壓力測試模擬")
st.markdown(f"基於 **{MSTR_BTC_HOLDINGS:,} BTC** 持倉，官方 CEBE 計算法（BTC數量口徑），模擬 BTC $40,000 ~ $200,000 每股真實淨值區間：")

sim_prices = list(range(40000, 200001, 10000))
rows = []
for p in sim_prices:
    sim_claims_btc    = (MSTR_TOTAL_DEBT_M + MSTR_TOTAL_PREF_M - MSTR_CASH_RESERVE_M) * 1e6 / p
    sim_common_btc    = MSTR_BTC_HOLDINGS - sim_claims_btc
    sim_cebe_sats     = sim_common_btc / MSTR_FDSO * 1e8 if MSTR_FDSO > 0 else 0
    sim_cebe_usd      = sim_cebe_sats / 1e8 * p
    sim_drag          = sim_claims_btc / MSTR_BTC_HOLDINGS * 100
    rows.append({
        "BTC 模擬價格":            f"${p:,.0f}",
        "每股 CEBE（sats）":       f"{sim_cebe_sats:,.0f}",
        "每股 CEBE（USD）":        f"${sim_cebe_usd:,.2f}",
        "Drag（債務侵蝕率）":       f"{sim_drag:.1f}%",
        "1.0x 清算價值":           f"${sim_cebe_usd * 1.0:,.2f}",
        "1.1x":                    f"${sim_cebe_usd * 1.1:,.2f}",
        "1.2x 合理防線":           f"${sim_cebe_usd * 1.2:,.2f}",
        "1.3x":                    f"${sim_cebe_usd * 1.3:,.2f}",
        "1.4x":                    f"${sim_cebe_usd * 1.4:,.2f}",
        "1.5x":                    f"${sim_cebe_usd * 1.5:,.2f}",
        "1.6x 泡沫警戒":           f"${sim_cebe_usd * 1.6:,.2f}",
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.markdown("""
<div style="background:#181a20;border:1px solid #2b3139;border-radius:8px;padding:16px;margin:12px 0;">
    <p style="color:#fff;font-size:13px;font-weight:bold;margin-bottom:10px;">💡 如何解讀此表？</p>
    <ul style="color:#fff;font-size:12px;line-height:1.7;padding-left:18px;">
        <li><b>每股 CEBE sats</b>：不受 BTC 價格影響，是衡量每股含金量的穩定指標，越高越好。</li>
        <li><b>每股 CEBE USD</b>：真實清算價值，股價應在此基礎上給予溢價。</li>
        <li><b>Drag</b>：BTC 越漲，侵蝕率越低，普通股股東受益越多。</li>
        <li><b>1.0x</b>：清算警戒線，股價跌到此處代表市場開始定價清算風險。</li>
        <li><b>1.2x</b>：歷史合理防線，左側抄底參考點。</li>
        <li><b>1.6x</b>：泡沫警戒，超過此線需謹慎追多。</li>
    </ul>
</div>
""", unsafe_allow_html=True)
