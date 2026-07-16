import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math

# ==========================================
# 0. 頁面設定
# ==========================================
st.set_page_config(
    page_title="MSTR 股價追蹤分析儀",
    layout="wide",
    initial_sidebar_state="expanded"
)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# ==========================================
# 全域 CSS
# ==========================================
st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] {
    background-color: #0d1117 !important;
    color: #c9d1d9 !important;
    font-family: 'SF Mono', 'Fira Code', monospace;
}
[data-testid="stHeader"] { background: rgba(0,0,0,0); }
[data-testid="stSidebar"] { background-color: #161b22 !important; }
footer { visibility: hidden; }

.kpi-box {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 10px;
}
.kpi-label { font-size: 11px; color: #8b949e; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.kpi-value { font-size: 22px; font-weight: 700; font-family: 'SF Mono', monospace; }
.kpi-sub   { font-size: 11px; color: #8b949e; margin-top: 3px; }

.signal-box {
    border-radius: 8px;
    padding: 18px 20px;
    margin-bottom: 12px;
    border-left: 4px solid;
}
.signal-bull  { background:#0d2818; border-color:#238636; }
.signal-bear  { background:#2d1517; border-color:#da3633; }
.signal-neut  { background:#1c1f26; border-color:#6e7681; }

.signal-title { font-size: 13px; font-weight: 700; margin-bottom: 5px; }
.signal-desc  { font-size: 12px; color: #8b949e; line-height: 1.6; }

.cc-box {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    margin-top: 10px;
}

.tag-green { background:#238636; color:#fff; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; }
.tag-red   { background:#da3633; color:#fff; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; }
.tag-gray  { background:#30363d; color:#c9d1d9; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; }
.tag-yellow{ background:#9e6a03; color:#fff; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. Session State：備兌買權部位參數
# ==========================================
CC_DEFAULTS = {
    "cc_shares":      300,
    "cc_cost":        201.0,
    "cc_contracts":   3,
    "cc_strike":      134.0,
    "cc_expiry":      "2026-07-31",
    "cc_premium":     560.0,
}
for k, v in CC_DEFAULTS.items():
    if f"{k}_val" not in st.session_state:
        st.session_state[f"{k}_val"] = v

def save_cc():
    for k in CC_DEFAULTS:
        if k in st.session_state:
            st.session_state[f"{k}_val"] = st.session_state[k]

# ==========================================
# 2. 側邊欄：部位設定
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ 我的 MSTR 部位設定")
    st.caption("修改後自動儲存，刷新頁面保留數值")

    cc_shares = st.number_input("持股數量（股）",
        value=st.session_state["cc_shares_val"], step=100,
        key="cc_shares", on_change=save_cc)
    cc_cost = st.number_input("持股平均成本（$）",
        value=st.session_state["cc_cost_val"], step=1.0,
        key="cc_cost", on_change=save_cc)

    st.markdown("---")
    st.markdown("### 📋 備兌買權部位（Covered Call）")

    cc_contracts = st.number_input("賣出口數",
        value=st.session_state["cc_contracts_val"], step=1,
        key="cc_contracts", on_change=save_cc)
    cc_strike = st.number_input("履約價（$）",
        value=st.session_state["cc_strike_val"], step=1.0,
        key="cc_strike", on_change=save_cc)
    cc_expiry = st.text_input("到期日（YYYY-MM-DD）",
        value=st.session_state["cc_expiry_val"],
        key="cc_expiry", on_change=save_cc)
    cc_premium = st.number_input("已收權利金總額（$）",
        value=st.session_state["cc_premium_val"], step=10.0,
        key="cc_premium", on_change=save_cc)

    st.markdown("---")
    st.markdown("### 🔗 數據來源")
    st.caption("✅ MSTR 股價 / 選擇權鏈 → yfinance")
    st.caption("✅ BTC 價格 / 200WMA → yfinance")
    st.caption("✅ 隱含波動率 / Greeks → yfinance 選擇權鏈")
    st.caption("✅ 資金費率 → Binance REST API")
    st.caption("✅ 恐懼貪婪指數 → Alternative.me")
    st.caption("⚠️ 空頭興趣 → FINRA 每兩週更新，無即時免費API")

# ==========================================
# 3. 數據抓取函數
# ==========================================
@st.cache_data(ttl=60)
def fetch_mstr_data():
    try:
        mstr = yf.Ticker("MSTR")
        info = mstr.info
        hist = mstr.history(period="6mo", interval="1d")
        price = float(hist['Close'].iloc[-1]) if not hist.empty else 0
        # 歷史波動率 30 天
        if len(hist) >= 30:
            returns = np.log(hist['Close'] / hist['Close'].shift(1)).dropna()
            hv30 = float(returns.tail(30).std() * np.sqrt(252))
        else:
            hv30 = 0
        # Beta (對 BTC)
        btc_hist = yf.Ticker("BTC-USD").history(period="3mo", interval="1d")
        beta_btc = 0
        if not hist.empty and not btc_hist.empty:
            mstr_ret = hist['Close'].pct_change().dropna()
            btc_ret  = btc_hist['Close'].pct_change().dropna()
            common   = mstr_ret.index.intersection(btc_ret.index)
            if len(common) > 10:
                cov = np.cov(mstr_ret.loc[common], btc_ret.loc[common])[0][1]
                var = np.var(btc_ret.loc[common])
                beta_btc = cov / var if var != 0 else 0
        return {
            'price': price,
            'hv30':  hv30,
            'beta_btc': beta_btc,
            'hist':  hist,
            'info':  info,
        }
    except:
        return None

@st.cache_data(ttl=300)
def fetch_mstr_options():
    """抓最近到期日的選擇權，取得 ATM 附近的 IV、Delta"""
    try:
        mstr  = yf.Ticker("MSTR")
        exps  = mstr.options
        if not exps:
            return None
        # 取最近 2 個到期日
        results = []
        for exp in exps[:3]:
            chain = mstr.option_chain(exp)
            calls = chain.calls.copy()
            puts  = chain.puts.copy()
            results.append({'expiry': exp, 'calls': calls, 'puts': puts})
        return results
    except:
        return None

@st.cache_data(ttl=30)
def fetch_btc_data():
    try:
        btc   = yf.Ticker("BTC-USD")
        hist  = btc.history(period="2d", interval="5m")
        hist_d = btc.history(period="max", interval="1wk")
        price = float(hist['Close'].iloc[-1]) if not hist.empty else 0
        delta = 0
        if len(hist) > 1:
            prev = float(hist['Close'].iloc[0])
            delta = ((price - prev) / prev) * 100
        ma200w = 0
        if not hist_d.empty and len(hist_d) >= 200:
            hist_d = hist_d.reset_index()
            hist_d['200WMA'] = hist_d['Close'].rolling(200).mean()
            ma200w = float(hist_d['200WMA'].iloc[-1])
        return {'price': price, 'delta': delta, 'ma200w': ma200w}
    except:
        return None

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
        url  = "https://api.alternative.me/fng/?limit=1"
        data = requests.get(url, timeout=8).json()
        return int(data["data"][0]["value"])
    except:
        return 50

# ==========================================
# 4. Black-Scholes Greeks 計算
# ==========================================
def bs_greeks(S, K, T, r, sigma, option_type='call'):
    """S=股價, K=履約價, T=到期年份, r=無風險利率, sigma=IV"""
    if T <= 0 or sigma <= 0 or S <= 0:
        return {'delta': 0, 'theta': 0, 'vega': 0, 'price': 0, 'prob_itm': 0}
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        from scipy.stats import norm
        if option_type == 'call':
            delta    = norm.cdf(d1)
            price    = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            prob_itm = norm.cdf(d2)
        else:
            delta    = norm.cdf(d1) - 1
            price    = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            prob_itm = norm.cdf(-d2)
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * norm.cdf(d2 if option_type=='call' else -d2)) / 365
        vega  = S * norm.pdf(d1) * math.sqrt(T) / 100
        return {'delta': delta, 'theta': theta, 'vega': vega, 'price': price, 'prob_itm': prob_itm}
    except:
        return {'delta': 0, 'theta': 0, 'vega': 0, 'price': 0, 'prob_itm': 0}

# ==========================================
# 5. 主頁面開始
# ==========================================
st.markdown(f"""
<div style="padding:12px 0 20px 0; border-bottom:1px solid #30363d; margin-bottom:24px;">
    <div style="font-size:22px; font-weight:700; color:#e6edf3; letter-spacing:-0.5px;">
        📡 MSTR 多維追蹤分析儀
    </div>
    <div style="font-size:12px; color:#8b949e; margin-top:4px;">
        即時整合 BTC、選擇權、衍生品、情緒指標 ｜ 更新時間：{datetime.now(TAIPEI_TZ).strftime('%Y-%m-%d %H:%M:%S')} 台北時間
    </div>
</div>
""", unsafe_allow_html=True)

# ── 抓取所有數據 ──────────────────────────────────────────
with st.spinner("載入即時數據中..."):
    mstr_data  = fetch_mstr_data()
    mstr_opts  = fetch_mstr_options()
    btc_data   = fetch_btc_data()
    funding    = fetch_funding_rate()
    fng        = fetch_fear_greed()

mstr_price = mstr_data['price']  if mstr_data  else 0
btc_price  = btc_data['price']   if btc_data   else 0
ma200w     = btc_data['ma200w']  if btc_data   else 0
hv30       = mstr_data['hv30']   if mstr_data  else 0
beta_btc   = mstr_data['beta_btc'] if mstr_data else 0

# ── ATM IV 從選擇權鏈取得 ─────────────────────────────────
atm_iv = hv30  # 預設用歷史波動率
atm_iv_source = "歷史波動率（HV30，選擇權鏈備援）"
if mstr_opts and mstr_price > 0:
    try:
        calls = mstr_opts[0]['calls']
        calls_valid = calls[calls['impliedVolatility'] > 0].copy()
        calls_valid['dist'] = abs(calls_valid['strike'] - mstr_price)
        atm_row = calls_valid.sort_values('dist').iloc[0]
        atm_iv  = float(atm_row['impliedVolatility'])
        atm_iv_source = f"ATM Call IV（履約價 ${atm_row['strike']:.0f}，到期 {mstr_opts[0]['expiry']}）"
    except:
        pass

# ==========================================
# 6. 第一列：核心 KPI
# ==========================================
st.markdown("#### 📊 核心即時指標")
c1, c2, c3, c4, c5, c6 = st.columns(6)

def kpi(col, label, value, sub="", color="#e6edf3"):
    col.markdown(f"""
    <div class="kpi-box">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value" style="color:{color};">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)

mstr_chg_color = "#238636" if mstr_price >= cc_cost else "#da3633"
btc_chg_color  = "#238636" if btc_data and btc_data['delta'] >= 0 else "#da3633"
fng_color      = "#238636" if fng <= 30 else ("#da3633" if fng >= 70 else "#8b949e")
funding_color  = "#da3633" if funding < 0 else "#8b949e"

kpi(c1, "MSTR 股價", f"${mstr_price:.2f}",
    f"成本 ${cc_cost:.2f}｜{'盈利' if mstr_price >= cc_cost else '虧損'} ${abs(mstr_price - cc_cost):.2f}",
    mstr_chg_color)
kpi(c2, "BTC 即時價格", f"${btc_price:,.0f}",
    f"24H {btc_data['delta']:+.2f}%" if btc_data else "N/A",
    btc_chg_color)
kpi(c3, "隱含波動率 IV", f"{atm_iv*100:.1f}%",
    atm_iv_source[:30] + "...", "#f0883e")
kpi(c4, "歷史波動率 HV30", f"{hv30*100:.1f}%",
    f"IV/HV = {atm_iv/hv30:.2f}x（>1 賣權利金有利）" if hv30 > 0 else "",
    "#f0883e" if atm_iv > hv30 else "#8b949e")
kpi(c5, "恐懼貪婪指數", f"{fng}/100",
    "😱極恐懼" if fng<=25 else "😟恐懼" if fng<=45 else "😐中性" if fng<=55 else "😏貪婪" if fng<=75 else "🤑極貪婪",
    fng_color)
kpi(c6, "BTC 資金費率", f"{funding*100:+.4f}%",
    "空頭過熱 / 多頭清算" if funding < 0 else "多空平衡 / 多頭略佔優",
    funding_color)

# ==========================================
# 7. 第二列：Beta + 200WMA + 部位損益
# ==========================================
c7, c8, c9 = st.columns(3)

dist_200w = ((btc_price - ma200w) / ma200w * 100) if ma200w > 0 else 0
kpi(c7, "MSTR / BTC Beta", f"{beta_btc:.2f}x",
    f"BTC 漲/跌 1%，MSTR 預期 {beta_btc:.2f}%", "#a5d6ff")
kpi(c8, "BTC 200週均線", f"${ma200w:,.0f}",
    f"現價距離 200WMA：{dist_200w:+.1f}%",
    "#238636" if dist_200w > 10 else "#da3633" if dist_200w < 5 else "#f0883e")

# 持倉即時損益
total_cost    = cc_shares * cc_cost
current_value = cc_shares * mstr_price
pnl_stock     = current_value - total_cost
pnl_pct       = pnl_stock / total_cost * 100
net_pnl       = pnl_stock + cc_premium
net_pnl_color = "#238636" if net_pnl >= 0 else "#da3633"
kpi(c9, "持倉淨損益（含收租）",
    f"${net_pnl:+,.0f}",
    f"股票 ${pnl_stock:+,.0f}（{pnl_pct:+.1f}%）+ 權利金 ${cc_premium:.0f}",
    net_pnl_color)

# ==========================================
# 8. 圖表區：MSTR 股價走勢 + 選擇權 Greeks
# ==========================================
st.markdown("---")
col_chart, col_greeks = st.columns([1.6, 1])

with col_chart:
    st.markdown("#### 📈 MSTR 6個月股價走勢")
    if mstr_data and not mstr_data['hist'].empty:
        hist = mstr_data['hist'].copy()
        hist['MA20'] = hist['Close'].rolling(20).mean()
        hist['MA60'] = hist['Close'].rolling(60).mean()

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'],
            low=hist['Low'],  close=hist['Close'],
            name='MSTR', increasing_line_color='#238636', decreasing_line_color='#da3633'
        ))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA20'], name='MA20',
            line=dict(color='#f0883e', width=1.2)))
        fig.add_trace(go.Scatter(x=hist.index, y=hist['MA60'], name='MA60',
            line=dict(color='#a5d6ff', width=1.2, dash='dash')))
        # 成本線
        fig.add_hline(y=cc_cost, line_color='#da3633', line_dash='dot',
            annotation_text=f"持倉成本 ${cc_cost}", annotation_font_color='#da3633')
        # 履約價線
        fig.add_hline(y=cc_strike, line_color='#f0883e', line_dash='dash',
            annotation_text=f"備兌履約價 ${cc_strike}", annotation_font_color='#f0883e')
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, tickfont=dict(color='#8b949e'), rangeslider_visible=False),
            yaxis=dict(showgrid=True, gridcolor='#21262d', tickfont=dict(color='#8b949e')),
            legend=dict(font=dict(color='#8b949e', size=11), orientation='h', y=1.05),
            height=360, margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    else:
        st.warning("無法載入 MSTR 歷史數據")

with col_greeks:
    st.markdown("#### 🔢 備兌買權 Greeks 即時計算")

    # 計算到期天數
    try:
        exp_date = datetime.strptime(cc_expiry, "%Y-%m-%d")
        days_to_exp = max(0, (exp_date - datetime.now()).days)
        T = days_to_exp / 365
    except:
        days_to_exp = 30
        T = 30 / 365

    r     = 0.045  # 無風險利率
    greeks = bs_greeks(mstr_price, cc_strike, T, r, atm_iv, 'call')
    prob_assign = greeks['prob_itm'] * 100

    # IV/HV 比較
    iv_hv_ratio = atm_iv / hv30 if hv30 > 0 else 1.0
    iv_hv_signal = "🟢 IV > HV，賣權利金時機佳" if iv_hv_ratio > 1.1 else \
                   "🟡 IV ≈ HV，普通時機" if iv_hv_ratio > 0.9 else \
                   "🔴 IV < HV，賣出不划算"

    st.markdown(f"""
    <div class="cc-box">
        <div style="font-size:12px; color:#8b949e; margin-bottom:14px;">
            基於 B-S 模型 ｜ 到期剩 <b style="color:#e6edf3;">{days_to_exp} 天</b>
            ｜ IV = <b style="color:#f0883e;">{atm_iv*100:.1f}%</b>
        </div>

        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:14px;">
            <div>
                <div style="font-size:10px;color:#8b949e;">Delta（Δ）</div>
                <div style="font-size:20px;font-weight:700;color:#a5d6ff;">{greeks['delta']:.3f}</div>
                <div style="font-size:10px;color:#8b949e;">被指派機率</div>
            </div>
            <div>
                <div style="font-size:10px;color:#8b949e;">Theta（Θ）/天</div>
                <div style="font-size:20px;font-weight:700;color:#238636;">{greeks['theta']:+.3f}</div>
                <div style="font-size:10px;color:#8b949e;">每天時間價值衰減</div>
            </div>
            <div>
                <div style="font-size:10px;color:#8b949e;">Vega（V）/ 1% IV</div>
                <div style="font-size:20px;font-weight:700;color:#f0883e;">{greeks['vega']:.3f}</div>
                <div style="font-size:10px;color:#8b949e;">IV 變動影響</div>
            </div>
            <div>
                <div style="font-size:10px;color:#8b949e;">理論選擇權價格</div>
                <div style="font-size:20px;font-weight:700;color:#e6edf3;">${greeks['price']:.2f}</div>
                <div style="font-size:10px;color:#8b949e;">3口 = ${greeks['price']*300:.0f}</div>
            </div>
        </div>

        <div style="background:#0d1117; border-radius:6px; padding:12px; margin-bottom:10px;">
            <div style="font-size:11px; color:#8b949e; margin-bottom:6px;">履約被指派機率</div>
            <div style="background:#21262d; border-radius:4px; height:8px; overflow:hidden;">
                <div style="background:{'#da3633' if prob_assign>50 else '#f0883e' if prob_assign>30 else '#238636'};
                     width:{prob_assign:.0f}%; height:100%;"></div>
            </div>
            <div style="font-size:13px; font-weight:700; margin-top:6px;
                 color:{'#da3633' if prob_assign>50 else '#f0883e' if prob_assign>30 else '#238636'};">
                {prob_assign:.1f}% 機率被指派
            </div>
        </div>

        <div style="font-size:11px; color:#8b949e;">{iv_hv_signal}</div>
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 9. 選擇權鏈：ATM 附近 5 個履約價
# ==========================================
st.markdown("---")
st.markdown("#### 📋 MSTR 選擇權鏈（ATM 附近，最近到期）")

if mstr_opts and mstr_price > 0:
    try:
        first_exp = mstr_opts[0]
        calls = first_exp['calls'].copy()
        puts  = first_exp['puts'].copy()

        # 取 ATM 附近 6 個
        calls['dist'] = abs(calls['strike'] - mstr_price)
        atm_calls = calls.sort_values('dist').head(7).sort_values('strike')

        display_df = atm_calls[['strike','lastPrice','bid','ask','impliedVolatility','openInterest','volume']].copy()
        display_df.columns = ['履約價','最新成交','Bid','Ask','IV','未平倉量','成交量']
        display_df['IV']   = (display_df['IV'] * 100).round(1).astype(str) + '%'
        display_df['履約價'] = display_df['履約價'].apply(lambda x: f"${x:.0f}" + (" ← ATM" if abs(x - mstr_price) == display_df['dist'].min() else ""))
        display_df['未平倉量'] = display_df['未平倉量'].astype(int)
        display_df['成交量']   = display_df['成交量'].astype(int)

        st.caption(f"到期日：{first_exp['expiry']}｜MSTR 現價 ${mstr_price:.2f}｜Call 選擇權（賣備兌買權參考）")
        st.dataframe(display_df.reset_index(drop=True), use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"選擇權鏈載入失敗：{e}")
else:
    st.warning("無法載入選擇權鏈數據")

# ==========================================
# 10. 訊號面板
# ==========================================
st.markdown("---")
st.markdown("#### 🚦 多維訊號綜合判讀")

sig_col1, sig_col2 = st.columns(2)

with sig_col1:
    st.markdown("**BTC / 宏觀訊號**")

    # 200WMA 訊號
    if dist_200w < 5:
        st.markdown('<div class="signal-box signal-bull"><div class="signal-title" style="color:#238636;">🟢 BTC 逼近 200週均線</div><div class="signal-desc">歷史上極少跌破，現價距 200WMA 僅 {:.1f}%，為長線大底防禦區，左側抄底信號強。</div></div>'.format(dist_200w), unsafe_allow_html=True)
    elif dist_200w > 50:
        st.markdown('<div class="signal-box signal-bear"><div class="signal-title" style="color:#da3633;">🔴 BTC 大幅高於 200週均線</div><div class="signal-desc">現價高於 200WMA {:.1f}%，歷史上此區間為牛市後期，注意回調風險。</div></div>'.format(dist_200w), unsafe_allow_html=True)
    else:
        st.markdown('<div class="signal-box signal-neut"><div class="signal-title" style="color:#8b949e;">⚪ BTC 200週均線：正常區間</div><div class="signal-desc">現價高於 200WMA {:.1f}%，處於正常多頭軌道，無特殊訊號。</div></div>'.format(dist_200w), unsafe_allow_html=True)

    # 資金費率訊號
    if funding < -0.0002:
        st.markdown('<div class="signal-box signal-bull"><div class="signal-title" style="color:#238636;">🟢 資金費率深度負值</div><div class="signal-desc">BTCUSDT 費率 {:+.4f}%，代表空頭過熱、多頭清算完畢，為歷史高勝率反彈訊號。</div></div>'.format(funding*100), unsafe_allow_html=True)
    elif funding > 0.0005:
        st.markdown('<div class="signal-box signal-bear"><div class="signal-title" style="color:#da3633;">🔴 資金費率偏高</div><div class="signal-desc">BTCUSDT 費率 {:+.4f}%，多頭槓桿過熱，短期回調風險上升。</div></div>'.format(funding*100), unsafe_allow_html=True)
    else:
        st.markdown('<div class="signal-box signal-neut"><div class="signal-title" style="color:#8b949e;">⚪ 資金費率：中性</div><div class="signal-desc">BTCUSDT 費率 {:+.4f}%，多空槓桿平衡，無明顯方向訊號。</div></div>'.format(funding*100), unsafe_allow_html=True)

    # 恐懼貪婪
    if fng <= 25:
        st.markdown(f'<div class="signal-box signal-bull"><div class="signal-title" style="color:#238636;">🟢 市場極度恐懼（{fng}/100）</div><div class="signal-desc">歷史上極度恐懼區間為優質買點，散戶情緒低迷往往是主力建倉時機。</div></div>', unsafe_allow_html=True)
    elif fng >= 75:
        st.markdown(f'<div class="signal-box signal-bear"><div class="signal-title" style="color:#da3633;">🔴 市場極度貪婪（{fng}/100）</div><div class="signal-desc">市場情緒過熱，警惕散戶追高風險，建議減少槓桿。</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="signal-box signal-neut"><div class="signal-title" style="color:#8b949e;">⚪ 市場情緒中性（{fng}/100）</div><div class="signal-desc">情緒溫度正常，無極端訊號。</div></div>', unsafe_allow_html=True)

with sig_col2:
    st.markdown("**MSTR / 選擇權訊號**")

    # IV/HV 比較 → 備兌買權時機
    if iv_hv_ratio > 1.15:
        st.markdown(f'<div class="signal-box signal-bull"><div class="signal-title" style="color:#238636;">🟢 IV 顯著高於 HV（{iv_hv_ratio:.2f}x）</div><div class="signal-desc">隱含波動率溢價明顯，賣出備兌買權收取的權利金高於統計公平值，為賣方有利時機。</div></div>', unsafe_allow_html=True)
    elif iv_hv_ratio < 0.9:
        st.markdown(f'<div class="signal-box signal-bear"><div class="signal-title" style="color:#da3633;">🔴 IV 低於 HV（{iv_hv_ratio:.2f}x）</div><div class="signal-desc">隱含波動率被低估，賣出選擇權收取的權利金偏低，此時賣備兌買權性價比差。</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="signal-box signal-neut"><div class="signal-title" style="color:#8b949e;">⚪ IV/HV 比值中性（{iv_hv_ratio:.2f}x）</div><div class="signal-desc">IV 與歷史波動率接近，賣出選擇權屬正常定價，無特別有利或不利訊號。</div></div>', unsafe_allow_html=True)

    # Delta 訊號 → 履約風險
    if prob_assign > 60:
        st.markdown(f'<div class="signal-box signal-bear"><div class="signal-title" style="color:#da3633;">🔴 當前履約被指派機率高（{prob_assign:.1f}%）</div><div class="signal-desc">備兌買權被執行風險高，持股可能以 ${cc_strike:.0f} 被買走。若不願被指派，考慮向上移倉（Roll Up）或買回平倉。</div></div>', unsafe_allow_html=True)
    elif prob_assign > 35:
        st.markdown(f'<div class="signal-box signal-neut"><div class="signal-title" style="color:#8b949e;">⚠️ 履約被指派機率中等（{prob_assign:.1f}%）</div><div class="signal-desc">需持續關注股價走勢，若 MSTR 持續上漲接近履約價 ${cc_strike:.0f}，應提前評估是否移倉。</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="signal-box signal-bull"><div class="signal-title" style="color:#238636;">🟢 履約被指派機率低（{prob_assign:.1f}%）</div><div class="signal-desc">備兌買權被執行機率低，持股安全，預期到期作廢全額保留權利金。</div></div>', unsafe_allow_html=True)

    # Beta 預測
    expected_mstr_move = btc_data['delta'] * beta_btc if btc_data else 0
    if abs(expected_mstr_move) > 3:
        color = "#238636" if expected_mstr_move > 0 else "#da3633"
        st.markdown(f'<div class="signal-box {"signal-bull" if expected_mstr_move > 0 else "signal-bear"}"><div class="signal-title" style="color:{color};">{"📈" if expected_mstr_move > 0 else "📉"} BTC Beta 預期 MSTR 大幅波動</div><div class="signal-desc">BTC 今日 {btc_data["delta"]:+.2f}%，依 Beta {beta_btc:.2f}x 推算，MSTR 預期波動 {expected_mstr_move:+.1f}%（約 ${mstr_price * expected_mstr_move / 100:+.2f}）。</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="signal-box signal-neut"><div class="signal-title" style="color:#8b949e;">⚪ BTC Beta 預測：小幅波動</div><div class="signal-desc">BTC 今日 {btc_data["delta"] if btc_data else 0:+.2f}%，依 Beta {beta_btc:.2f}x 推算，MSTR 預期波動 {expected_mstr_move:+.1f}%，影響有限。</div></div>', unsafe_allow_html=True)

# ==========================================
# 11. 備兌買權下一輪滾動建議
# ==========================================
st.markdown("---")
st.markdown("#### 🎯 備兌買權下一輪滾動履約價建議")

if mstr_price > 0 and atm_iv > 0:
    roll_data = []
    # 計算不同 Delta 目標下的建議履約價
    for target_delta, label, strategy in [
        (0.20, "保守（低被指派風險）", "適合看好 MSTR 長線，以保留上漲空間為主"),
        (0.30, "平衡（推薦）", "Delta 0.3 甜蜜點，兼顧收租與上漲空間"),
        (0.40, "積極（高收租）", "權利金最高，但被指派風險較大"),
    ]:
        # 用二分法反推對應履約價
        lo, hi = mstr_price, mstr_price * 3
        for _ in range(50):
            mid = (lo + hi) / 2
            g = bs_greeks(mstr_price, mid, 30/365, 0.045, atm_iv, 'call')
            if g['delta'] > target_delta:
                lo = mid
            else:
                hi = mid
        suggested_k = round(mid / 5) * 5  # 取最近 5 的倍數
        g_check = bs_greeks(mstr_price, suggested_k, 30/365, 0.045, atm_iv, 'call')
        premium_est = g_check['price'] * 100 * cc_contracts
        roll_data.append({
            "策略":      label,
            "建議履約價": f"${suggested_k:.0f}",
            "距現價":    f"+{(suggested_k/mstr_price-1)*100:.1f}%",
            "Delta":    f"{g_check['delta']:.2f}",
            "預估每月權利金（3口）": f"${premium_est:.0f}",
            "策略說明":  strategy,
        })

    st.dataframe(pd.DataFrame(roll_data), use_container_width=True, hide_index=True)

    # 損益平衡計算
    total_premium_needed = (cc_cost - mstr_price) * cc_shares
    st.markdown(f"""
    <div class="cc-box" style="margin-top:14px;">
        <div style="font-size:13px; font-weight:700; color:#e6edf3; margin-bottom:10px;">📊 收租還本計算</div>
        <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; font-size:12px;">
            <div>
                <div style="color:#8b949e;">目前帳面虧損</div>
                <div style="color:#da3633; font-size:16px; font-weight:700;">${abs(pnl_stock):,.0f}</div>
            </div>
            <div>
                <div style="color:#8b949e;">已累計收取權利金</div>
                <div style="color:#238636; font-size:16px; font-weight:700;">${cc_premium:,.0f}</div>
            </div>
            <div>
                <div style="color:#8b949e;">還需再收</div>
                <div style="color:#f0883e; font-size:16px; font-weight:700;">${max(0, abs(pnl_stock) - cc_premium):,.0f}</div>
            </div>
        </div>
        <div style="margin-top:12px; font-size:11px; color:#8b949e;">
            ※ 以平衡策略每月收 ${roll_data[1]['預估每月權利金（3口）'][1:]} 估算，
            約需 <b style="color:#e6edf3;">{max(0, abs(pnl_stock) - cc_premium) / max(1, float(roll_data[1]['預估每月權利金（3口）'][1:])):.0f} 個月</b>
            透過收租彌補虧損（不含股價本身回升）
        </div>
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 12. 數據說明
# ==========================================
with st.expander("📖 各指標數據來源與說明"):
    st.markdown(f"""
| 指標 | 數據來源 | 更新頻率 | 說明 |
|------|---------|---------|------|
| MSTR 股價 / 歷史走勢 | `yfinance` | 每 60 秒 | 美股收盤後延遲 15 分鐘 |
| BTC 即時價格 | `yfinance` BTC-USD | 每 30 秒 | 跨市場綜合報價 |
| BTC 200週均線 | `yfinance` 週線 | 每 30 秒 | 歷史大底防線 |
| 隱含波動率 IV | `yfinance` 選擇權鏈 | 每 5 分鐘 | ATM Call 選擇權 IV，{atm_iv_source} |
| 歷史波動率 HV30 | `yfinance` 計算 | 每 60 秒 | 30 天對數報酬年化標準差 |
| Beta（對 BTC） | `yfinance` 計算 | 每 60 秒 | 3 個月日報酬共變異數計算 |
| BTC 資金費率 | Binance USDT-M REST API | 每 30 秒 | BTCUSDT 永續合約費率 |
| 恐懼貪婪指數 | Alternative.me | 每 5 分鐘 | 0=極恐懼，100=極貪婪 |
| Greeks（Delta/Theta/Vega） | Black-Scholes 模型計算 | 即時 | 基於 yfinance IV 計算 |
| 空頭興趣 | ❌ 無免費即時 API | 每兩週 | FINRA 規定每月發布兩次，MarketBeat 等需付費 |
    """)
