"""
app.py — NetPulse 5G 기지국 모니터링 대시보드

5G 기지국 네트워크 KPI 모니터링, 서비스 품질 관리,
정기점검 현황, 데이터 품질 시각화.

실행: streamlit run app.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from spc import analyze_spc, control_chart_limits

# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="NetPulse — 5G NOC 대시보드",
    page_icon="📡",
    layout="wide",
)

st.title("📡 NetPulse — 5G 기지국 모니터링 대시보드")
st.caption("네트워크 KPI 모니터링 · 서비스 품질 관리 · 정기점검 · 데이터 품질 | Region: REGION_SEOUL_001")

# ============================================================
# 데이터 로드
# ============================================================

PROCESSED = "data/processed"

SPC_SPECS = {
    "latency_ms":       {"usl": 20.0,  "lsl": 3.0,   "unit": "ms",  "label": "E2E 지연시간"},
    "jitter_ms":        {"usl": 8.0,   "lsl": 0.5,   "unit": "ms",  "label": "지터"},
    "packet_loss_pct":  {"usl": 3.0,   "lsl": 0.0,   "unit": "%",   "label": "패킷 손실률"},
}


@st.cache_data
def load_data():
    data = {}
    paths = {
        "logs":         os.path.join(PROCESSED, "analyzed_logs_with_states.csv"),
        "judge":        os.path.join(PROCESSED, "scenario_judgement.csv"),
        "validation":   os.path.join(PROCESSED, "validation_result.csv"),
        "spc":          os.path.join(PROCESSED, "spc_analysis.csv"),
        "report":       os.path.join(PROCESSED, "operator_report.json"),
        "dq":           os.path.join(PROCESSED, "dq_assessment.csv"),
        "kpi_summary":  os.path.join(PROCESSED, "batch_kpi_summary.csv"),
        "escalation":   os.path.join(PROCESSED, "batch_escalation_candidates.csv"),
        "recon":        os.path.join(PROCESSED, "batch_reconciliation.csv"),
    }

    for key, path in paths.items():
        if os.path.exists(path):
            if path.endswith(".json"):
                with open(path, "r", encoding="utf-8") as f:
                    data[key] = json.load(f)
            else:
                data[key] = pd.read_csv(path)
    return data


data = load_data()

if "logs" not in data:
    st.error("파이프라인 결과 데이터가 없습니다. `python3 src/generate_logs.py && python3 src/main.py`를 먼저 실행하세요.")
    st.stop()

# ============================================================
# 탭 구성
# ============================================================

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 타임라인", "📈 서비스 품질(SPC)", "📡 셀 분석",
    "✅ 판정 요약", "🔄 정기점검", "🛡️ 데이터 품질"
])

logs = data["logs"]
scenarios = sorted(logs["scenario_id"].unique())

# ============================================================
# TAB 1: 타임라인
# ============================================================
with tab1:
    sel = st.selectbox("시나리오", scenarios, key="timeline_scenario")
    sub = logs[logs["scenario_id"] == sel].sort_values("timestamp")

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        subplot_titles=("Latency (ms)", "Jitter (ms)", "Packet Loss (%)"))

    state_colors = {"GREEN": "green", "YELLOW": "orange", "RED": "red",
                    "RECOVERING": "royalblue", "BLACKOUT": "black"}

    for i, col in enumerate(["latency_ms", "jitter_ms", "packet_loss_pct"], 1):
        colors = [state_colors.get(s, "gray") for s in sub["state"]]
        fig.add_trace(go.Scatter(x=sub["timestamp"], y=sub[col], mode="markers",
                                 marker=dict(color=colors, size=3), name=col), row=i, col=1)

    fig.update_layout(height=600, showlegend=False, title_text=f"시나리오 {sel} KPI 타임라인")
    st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TAB 2: 서비스 품질 (SPC)
# ============================================================
with tab2:
    sel2 = st.selectbox("시나리오", scenarios, key="spc_scenario")
    param = st.selectbox("KPI 파라미터", list(SPC_SPECS.keys()))

    spec = SPC_SPECS[param]
    sub2 = logs[logs["scenario_id"] == sel2].sort_values("timestamp")
    spc_result = analyze_spc(sub2, col=param, usl=spec["usl"], lsl=spec["lsl"])
    limits = spc_result["limits"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Cpk", f"{spc_result['cpk']:.4f}")
    col2.metric("Ppk", f"{spc_result['ppk']:.4f}")
    col3.metric("OOC", spc_result["ooc_count"])

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=sub2["timestamp"], y=sub2[param], mode="markers",
                              marker=dict(size=3, color="steelblue"), name=spec["label"]))
    fig2.add_hline(y=limits["ucl"], line_dash="dash", line_color="red", annotation_text="UCL")
    fig2.add_hline(y=limits["mean"], line_dash="solid", line_color="green", annotation_text="Mean")
    fig2.add_hline(y=limits["lcl"], line_dash="dash", line_color="red", annotation_text="LCL")
    fig2.add_hline(y=spec["usl"], line_dash="dot", line_color="purple", annotation_text="USL")
    fig2.add_hline(y=spec["lsl"], line_dash="dot", line_color="purple", annotation_text="LSL")
    fig2.update_layout(title=f"{sel2} — {spec['label']} Control Chart", height=400)
    st.plotly_chart(fig2, use_container_width=True)

# ============================================================
# TAB 3: 셀 분석
# ============================================================
with tab3:
    sel3 = st.selectbox("시나리오", scenarios, key="cell_scenario")
    sub3 = logs[logs["scenario_id"] == sel3]

    cell_stats = sub3.groupby("cell_id").agg(
        measurements=("timestamp", "count"),
        anomaly_count=("anomaly_flag", "sum"),
        avg_latency=("latency_ms", "mean"),
        max_latency=("latency_ms", "max"),
        avg_packet_loss=("packet_loss_pct", "mean"),
    ).round(2).reset_index()
    cell_stats["anomaly_ratio"] = (cell_stats["anomaly_count"] / cell_stats["measurements"]).round(4)

    st.dataframe(cell_stats.sort_values("anomaly_ratio", ascending=False), use_container_width=True)

# ============================================================
# TAB 4: 판정 요약
# ============================================================
with tab4:
    if "judge" in data:
        judge = data["judge"]
        st.subheader("시나리오별 최종 판정")
        st.dataframe(judge, use_container_width=True)

    if "validation" in data:
        val = data["validation"]
        st.subheader("검증 결과")
        st.dataframe(val, use_container_width=True)

# ============================================================
# TAB 5: 정기점검 (배치)
# ============================================================
with tab5:
    st.subheader("일일 KPI 집계")
    if "kpi_summary" in data:
        st.dataframe(data["kpi_summary"], use_container_width=True)

    st.subheader("에스컬레이션 후보")
    if "escalation" in data:
        esc = data["escalation"]
        if len(esc) > 0:
            priority_icons = {"URGENT": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
            esc["priority_icon"] = esc["priority"].map(priority_icons).fillna("")
            st.dataframe(esc, use_container_width=True)
        else:
            st.info("에스컬레이션 후보 없음")

    st.subheader("정합성 검증")
    if "recon" in data:
        st.dataframe(data["recon"], use_container_width=True)

# ============================================================
# TAB 6: 데이터 품질 (DQM)
# ============================================================
with tab6:
    st.subheader("측정 데이터 품질 평가")

    if "dq" in data:
        dq = data["dq"]
        grade_colors = {"A": "#28a745", "B": "#17a2b8", "C": "#ffc107", "D": "#dc3545"}

        cols = st.columns(len(dq))
        for i, (_, row) in enumerate(dq.iterrows()):
            color = grade_colors.get(row["grade"], "#6c757d")
            cols[i].markdown(
                f"<div style='text-align:center; padding:15px; border-radius:10px; "
                f"background-color:{color}22; border:2px solid {color}'>"
                f"<h3 style='color:{color}'>{row['grade']}</h3>"
                f"<p><b>{row['dimension']}</b></p>"
                f"<p>{row['score']:.1f}%</p></div>",
                unsafe_allow_html=True
            )

        st.markdown("---")
        st.caption("검증 기준: 완전성(30%) + 정합성(25%) + 적시성(20%) + 정확성(25%)")
