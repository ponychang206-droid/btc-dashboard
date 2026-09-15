import streamlit as st
import pandas as pd
import numpy as np
from scipy.stats import norm
import plotly.graph_objects as go
import plotly.express as px

# ── 頁面設定 ──────────────────────────────────────────────
st.set_page_config(
    page_title="MSTR Portfolio Analytics",
    page_layout="wide",
    initial_sidebar_state="expanded"
)

# ── 預設資料 (已修正到期日年份) ──────────────────────────────────
CC_POSITIONS_DEFAULT = [
    {"id": 1, "label": "Jan'27 $195", "strike": 195.0, "expiry": "2027-01-16", "contracts": 20, "avg_cost": 86.26, "active": True},
    {"id": 2, "label": "Nov26 $160",  "strike": 160.0, "expiry": "2026-11-20", "contracts": 6,  "avg_cost": 79.05, "active": True},
    {"id": 3, "label": "Jan'27 $190", "strike": 190.0, "expiry": "2027-01-16", "contracts": 1,  "avg_cost": 83.20, "active": True},
    {"id": 4, "label": "Sep25 $155",  "strike": 155.0, "expiry": "2025-09-25", "contracts": 2,  "avg_cost": 42.11, "active": True},
    {"id": 5, "label": "Dec26 $195",  "strike": 195.0, "expiry": "2026-12-18", "contracts": 1,  "avg_cost": 84.47, "active": True},
    {"id": 6, "label": "Dec26 $190",  "strike": 190.0, "expiry": "2026-12-18", "contracts": 1,  "avg_cost": -4.49, "active": True},
]

CSP_POSITIONS_DEFAULT = [
    {"id": 1, "label": "Aug26 $221", "strike": 221.0, "expiry": "2026-08-21", "contracts": 1, "avg_cost": 0.0, "active": True},
    {"id": 2, "label": "Aug26 $242", "strike": 242.0, "expiry": "2026-08-21", "contracts": 1, "avg_cost": 0.0, "active": True},
]

# ── Black-Scholes 計算公式 ────────────────────────────────
def black_scholes_call(S, K, T, r, sigma):
    if T <= 0:
        return max(0.0, S - K), 1.0 if S > K else 0.0, 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    delta = norm.cdf(d1)
    theta = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)
    return price, delta, theta / 365.0

# ── 初始化 Session State ─────────────────────────────────
if "cc_positions" not in st.session_state:
    st.session_state.cc_positions = CC_POSITIONS_DEFAULT
if "csp_positions" not in st.session_state:
    st.session_state.csp_positions = CSP_POSITIONS_DEFAULT

# ── 側邊欄：市場參數設定 ──────────────────────────────────
st.sidebar.header("⚙️ 市場參數設定")
spot_price = st.sidebar.number_input("MSTR 目前股價 ($)", value=175.0, step=1.0)
volatility = st.sidebar.slider("隱含波動率 (IV %)", min_value=10, max_value=200, value=75) / 100.0
risk_free_rate = st.sidebar.number_input("無風險利率 (%)", value=4.25, step=0.25) / 100.0

# ── 主頁面標題 ───────────────────────────────────────────
st.title("📈 MSTR 期權組合分析儀")

# ── 資料處理與計算 ───────────────────────────────────────
today = pd.to_datetime("today")

cc_df = pd.DataFrame(st.session_state.cc_positions)
if not cc_df.empty:
    cc_df["expiry_dt"] = pd.to_datetime(cc_df["expiry"])
    cc_df["days_left"] = (cc_df["expiry_dt"] - today).dt.days.clip(lower=0)
    
    # 計算期權理論價與希臘字母
    greeks = cc_df.apply(
        lambda r: black_scholes_call(spot_price, r["strike"], r["days_left"]/365.0, risk_free_rate, volatility),
        axis=1
    )
    cc_df["theo_price"] = [g[0] for g in greeks]
    cc_df["delta"] = [g[1] for g in greeks]
    cc_df["theta"] = [g[2] for g in greeks]
    
    # 組合影響（Covered Call 為短短權，Delta 與 Theta 需取負值）
    cc_df["total_delta"] = -cc_df["delta"] * cc_df["contracts"] * 100
    cc_df["total_theta"] = -cc_df["theta"] * cc_df["contracts"] * 100

# ── 儀表板關鍵指標 (KPIs) ─────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("MSTR 現價", f"${spot_price:.2f}")
with col2:
    total_contracts = cc_df[cc_df["active"]]["contracts"].sum() if not cc_df.empty else 0
    st.metric("Covered Call 總張數", f"{total_contracts} 張")
with col3:
    net_delta = cc_df[cc_df["active"]]["total_delta"].sum() if not cc_df.empty else 0
    st.metric("組合 Net Delta", f"{net_delta:.2f}")
with col4:
    net_theta = cc_df[cc_df["active"]]["total_theta"].sum() if not cc_df.empty else 0
    st.metric("每日時間價值衰減 (Theta)", f"${net_theta:.2f}/日")

st.markdown("---")

# ── 部位明細表格 ─────────────────────────────────────────
st.subheader("📋 備兌買權 (Covered Call) 部位明細")

if not cc_df.empty:
    display_df = cc_df[[
        "label", "strike", "expiry", "days_left", "contracts", 
        "avg_cost", "theo_price", "delta", "total_delta", "total_theta", "active"
    ]].copy()
    
    display_df.columns = [
        "部位名稱", "履約價 ($)", "到期日", "剩餘天數", "合約數", 
        "平均成本 ($)", "理論現價 ($)", "單張 Delta", "總 Delta", "每日 Theta ($)", "啟用"
    ]
    
    st.dataframe(
        display_df.style.format({
            "履約價 ($)": "{:.2f}",
            "平均成本 ($)": "{:.2f}",
            "理論現價 ($)": "{:.2f}",
            "單張 Delta": "{:.4f}",
            "總 Delta": "{:.2f}",
            "每日 Theta ($)": "{:.2f}",
        }),
        use_container_width=True
    )

# ── 圖表分析 ─────────────────────────────────────────────
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("⏳ 部位到期日與天數分佈")
    if not cc_df.empty:
        fig_days = px.bar(
            cc_df, x="label", y="days_left", text="days_left",
            labels={"label": "部位", "days_left": "剩餘天數"},
            title="各部位剩餘到期天數"
        )
        st.plotly_chart(fig_days, use_container_width=True)

with col_chart2:
    st.subheader("📊 各部位 Delta 暴露貢獻")
    if not cc_df.empty:
        fig_delta = px.bar(
            cc_df, x="label", y="total_delta", text_auto=".1f",
            labels={"label": "部位", "total_delta": "總 Delta"},
            title="部位 Delta 影響 (負值代表對沖/看空)"
        )
        st.plotly_chart(fig_delta, use_container_width=True)
