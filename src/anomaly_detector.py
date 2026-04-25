"""
anomaly_detector.py — 네트워크 KPI 이상 탐지 엔진

3GPP TS 32.111 알람 관리 및 NOC 운영 가이드라인의 장애 탐지 규칙을 구현한다.
각 측정에 대해 7개 기본 규칙 + 2개 강화 규칙을 적용하여
anomaly_flag(0/1)와 anomaly_reason(탐지 사유)을 부여한다.

규칙 체계:
  [기본 규칙]
  R1. 지연시간 초과 — latency_ms ≥ 18ms (5G SLA 위반)
  R2. 지연시간 급변 — |latency_diff| ≥ 5ms (순간 네트워크 불안정)
  R3. 패킷 손실 초과 — packet_loss_pct ≥ 3.0% (링크 품질 이상)
  R4. 패킷 손실 급증 — packet_loss_diff ≥ 1.0%
  R5. 장비 알람 — alarm_code ≠ 0
  R6. 측정 신호 손실 — jitter_ms ≤ 0.1ms (프로브 응답 불능)
  R7. 외부 간섭 — interference_flag = 1

  [강화 규칙]
  R8. 피크시간 혼잡 — 18~22시 + latency_ms ≥ 15ms
  R9. 핵심 셀 품질 저하 — 중요도 ≥ 4 + DATA 유형 + latency_ms ≥ 14ms
"""

import numpy as np
import pandas as pd


def detect_anomalies(df):
    """
    벡터화된 규칙 기반 이상 탐지.
    iterrows 대신 numpy 연산으로 10,000 row 기준 ~50x 성능 향상.

    Returns:
        DataFrame with anomaly_flag (0/1), anomaly_reason (str) 추가
    """
    df = df.copy()
    n = len(df)

    # 각 규칙별 boolean mask (vectorized)
    r1_latency_high = df["latency_ms"].values >= 18
    r2_latency_spike = np.abs(df["latency_diff"].values) >= 5
    r3_loss_high = df["packet_loss_pct"].values >= 3.0
    r4_loss_jump = df["packet_loss_diff"].values >= 1.0
    r5_alarm = df["alarm_code"].values != 0
    r6_measurement_loss = df["jitter_ms"].values <= 0.1
    r7_interference = df["interference_flag"].values == 1

    # 강화 규칙
    r8_peak_congestion = np.zeros(n, dtype=bool)
    r9_priority_degradation = np.zeros(n, dtype=bool)

    if "measurement_hour" in df.columns:
        hours = df["measurement_hour"].values
        r8_peak_congestion = ((hours >= 18) & (hours <= 22)) & (df["latency_ms"].values >= 15)

    if "cell_priority" in df.columns and "measurement_type" in df.columns:
        r9_priority_degradation = (
            (df["cell_priority"].values >= 4)
            & (df["measurement_type"].values == "DATA")
            & (df["latency_ms"].values >= 14)
        )

    # 규칙-레이블 매핑
    rule_map = [
        (r1_latency_high, "latency_high"),
        (r2_latency_spike, "latency_spike"),
        (r3_loss_high, "packet_loss_high"),
        (r4_loss_jump, "packet_loss_jump"),
        (r5_alarm, "alarm_detected"),
        (r6_measurement_loss, "measurement_loss"),
        (r7_interference, "interference_event"),
        (r8_peak_congestion, "peak_hour_congestion"),
        (r9_priority_degradation, "priority_cell_degradation"),
    ]

    # anomaly_reason 조합
    reasons = []
    any_flag = np.zeros(n, dtype=bool)

    for mask, label in rule_map:
        any_flag |= mask

    for i in range(n):
        row_reasons = [label for mask, label in rule_map if mask[i]]
        reasons.append("|".join(row_reasons) if row_reasons else "normal")

    df["anomaly_flag"] = any_flag.astype(int)
    df["anomaly_reason"] = reasons

    return df


def summarize_anomalies(df):
    """
    시나리오별 이상 탐지 건수 및 규칙별 분포 요약.
    """
    summary = (
        df.groupby("scenario_id")["anomaly_flag"]
        .sum()
        .reset_index()
        .rename(columns={"anomaly_flag": "anomaly_count"})
    )
    return summary


def get_rule_distribution(df):
    """
    전체 데이터셋의 규칙별 탐지 건수 분포.
    NOC 운영 리포트용.
    """
    all_reasons = "|".join(df[df["anomaly_flag"] == 1]["anomaly_reason"].tolist())
    rule_labels = [
        "latency_high", "latency_spike", "packet_loss_high",
        "packet_loss_jump", "alarm_detected", "measurement_loss",
        "interference_event", "peak_hour_congestion", "priority_cell_degradation",
    ]
    distribution = {}
    for label in rule_labels:
        distribution[label] = all_reasons.count(label)
    return distribution
