import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 設置您的 CryptoQuant API KEY
# ==========================================
# 請在下方單引號內填入您的真實 API KEY (例如: 'cq_abc123...')
CQ_API_KEY = 'BAv7d6YEjD2EZqlICC0cvfID7fkGAsszML384NkuLqiKfYVEpJoVOX'

st.set_page_config(page_title="BTC 抄底監控看板", layout="wide")
st.title("🔮 BTC 抄底監控看板 (CryptoQuant 實時復刻)")
st.caption(f"數據分析快照: {datetime.now().strftime('%Y-%m-%d')} | 5 訊號綜合評分系統")

HEADERS = {"Authorization": f"Bearer {CQ_API_KEY}"}

# ==========================================
# 2. 數據抓取模組 (Data Fetching)
# ==========================================
def fetch_cq_data(url):
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            # 配合 CryptoQuant V1 API 結構解析
            res_json = response.json()
            data = res_json.get('data', []) if 'data' in res_json else res_json.get('result', {}).get('data', [])
            if data:
                df = pd.DataFrame(data)
                return df
        return None
    except:
        return None

def fetch_fear_greed():
    try:
        res = requests.get("https://api.alternative.me/fng/?limit=1").json()
        return int(res['data'][0]['value'])
    except:
        return 50

# 實時抓取數據
df_sopr = fetch_cq_data("https://api.cryptoquant.com/v1/btc/market-indicator/sopr-ratio?window=day")
df_mvrv = fetch_cq_data("https://api.cryptoquant.com/v1/btc/market-indicator/mvrv?window=day")
df_nupl = fetch_cq_data("https://api.cryptoquant.com/v1/btc/network-indicator/nupl?window=day")
df_nrpl = fetch_cq_data("https://api.cryptoquant.com/v1/btc/network-indicator/nrpl?window=day")
fng_value = fetch_fear_greed()

# ==========================================
# 3. 訊號閾值微調與計分引擎 (Scoring Engine)
# ==========================================
s1_score, s2_score, s3_score, s4_score, s5_score = 0.0, 0.0, 0.0, 0.0, 0.0
btc_price = 73522.0 # 預設基準價

if df_mvrv is not None and not df_mvrv.empty:
    btc_price = float(df_mvrv.iloc[0].get('price', 73522.0))

    # S1: SOPR Ratio 
    current_sopr = float(df_sopr.iloc[0].get('value', 1.01)) if df_sopr is not None else 1.01
    s1_score = max(0.0, min(20.0, (1.02 - current_sopr) / (1.02 - 0.92) * 20))

    # S2: MVRV
    current_mvrv = float(df_mvrv.iloc[0].get('value', 1.36))
    s2_score = max(0.0, min(20.0, (2.2 - current_mvrv) / (2.2 - 1.4) * 20))

    # S3: NUPL 
    current_nupl = float(df_nupl.iloc[0].get('value', 0.118)) if df_nupl is not None else 0.118
    s3_score = max(0.0, min(20.0, (0.4 - current_nupl) / (0.4 - (-0.1)) * 20))

    # S4: NRPL
    current_nrpl = float(df_nrpl.iloc[0].get('value', -3600000000)) if df_nrpl is not None else -3600000000
    s4_score = max(0.0, min(20.0, (0 - current_nrpl) / (0 - (-40000000000)) * 20))

    # S5: 恐懼貪婪
    s5_score = max(0.0, min(20.0, (40 - fng_value) / (40 - 10) * 20))
else:
    # 模擬預設快照測試數據 (若未成功填入有效 KEY)
    s1_score, s2_score, s3_score, s4_score, s5_score = 0.0, 9.6, 0.0, 0.0, 6.0

total_score = s1_score + s2_score + s3_score + s4_score + s5_score

# ==========================================
# 4. 前端佈局與彩虹指針儀表 (高相容更新版)
# ==========================================
col_left, col_right = st.columns([1.2, 1])

with col_left:
    st.metric(label="BTC 當前價格 (USD)", value=f"${btc_price:,.2f}")
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = total_score,
        domain = {'x': [0, 1], 'y': [0, 1]},
        gauge = {
            'axis': {'range': [0, 100]},
            'steps': [
                {'range': [0, 20], 'color': '#2b2b2b'},     # 觀望區
                {'range': [20, 50], 'color': '#1f4e5b'},    # 輕倉分批
                {'range': [50, 75], 'color': '#1d6f42'},    # 重倉抄底
                {'range': [75, 100], 'color': '#d9534f'}    # 梭哈大底
            ],
        }
    ))
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.subheader("📋 當前指標分解讀數")
    st.info(f"S1 · SOPR 結構分: {s1_score:.1f} / 20")
    st.info(f"S2 · MVRV 偏差分: {s2_score:.1f} / 20")
    st.info(f"S3 · NUPL 未實現損失分: {s3_score:.1f} / 20")
    st.info(f"S4 · NRPL 實現資金分: {s4_score:.1f} / 20")
    st.info(f"S5 · 恐懼貪婪情緒分: {s5_score:.1f} / 20")
    
    st.success(f"**🔥 綜合大盤得分: {total_score:.1f} 分**")
