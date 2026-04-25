"""
state_engine.py — 기지국 상태 머신 (Cell State Machine)

각 측정의 이상 탐지 결과를 바탕으로 기지국 실시간 상태를 분류한다.
NOC의 기지국 모니터링 상태 전이 로직을 구현.

상태 정의:
  GREEN      : 정상 — 모든 KPI 정상 범위
  YELLOW     : 주의 — 단일 KPI 위반 (모니터링 강화)
  RED        : 위험 — 복합 KPI 위반 또는 심각한 단일 위반
  RECOVERING : 회복 — 장애 후 정상 복귀 진행 중
  BLACKOUT   : 장애 — 측정 신호 손실 또는 RED 30회 연속 (현장 출동 대상)

상태 전이 규칙:
  GREEN → YELLOW     : 단일 이상 탐지
  GREEN → RED        : 복합 이상 탐지 (신호손실, 알람+간섭 등)
  YELLOW → RED       : 복합 이상 조건 충족
  RED → BLACKOUT     : 30회 연속 RED 지속
  ANY_ANOMALY → RECOVERING : 이상 후 정상 측정 발생
  RECOVERING → GREEN : 이상 없이 정상 유지
"""

import pandas as pd


def assign_states(df):
    """
    anomaly 결과를 바탕으로 각 측정의 실시간 상태를 분류한다.
    시나리오별로 독립 실행 (각 시나리오는 별도의 상태 머신).
    """
    result = []

    for scenario_id, group in df.groupby("scenario_id"):
        g = group.sort_values("timestamp").copy()
        states = []

        prev_state = "GREEN"
        red_streak = 0

        for _, row in g.iterrows():
            reason = row["anomaly_reason"]

            is_measurement_loss = "measurement_loss" in reason
            is_alarm = "alarm_detected" in reason
            is_interference = "interference_event" in reason
            is_loss_high = "packet_loss_high" in reason or "packet_loss_jump" in reason
            is_latency_high = "latency_high" in reason or "latency_spike" in reason

            if row["anomaly_flag"] == 0:
                if prev_state in ["YELLOW", "RED", "BLACKOUT", "RECOVERING"]:
                    state = "RECOVERING"
                else:
                    state = "GREEN"
                red_streak = 0

            else:
                # 측정 신호 손실 → 즉시 BLACKOUT
                if is_measurement_loss:
                    state = "BLACKOUT"
                    red_streak += 1

                # 복합 이상 → RED
                elif is_alarm and (is_loss_high or is_latency_high or is_interference):
                    state = "RED"
                    red_streak += 1

                elif is_loss_high and is_latency_high:
                    state = "RED"
                    red_streak += 1

                # 단일 이상 → YELLOW
                elif is_alarm:
                    state = "YELLOW"
                    red_streak = 0

                elif is_loss_high or is_latency_high or is_interference:
                    state = "YELLOW"
                    red_streak = 0

                else:
                    state = "YELLOW"
                    red_streak = 0

            # RED 30회 연속 → BLACKOUT 에스컬레이션
            if red_streak >= 30:
                state = "BLACKOUT"

            states.append(state)
            prev_state = state

        g["state"] = states
        result.append(g)

    out = pd.concat(result, ignore_index=True)
    return out


def summarize_states(df):
    """시나리오별 상태 분포 요약."""
    summary = (
        df.groupby(["scenario_id", "state"])
        .size()
        .reset_index(name="count")
        .sort_values(["scenario_id", "state"])
    )
    return summary


def final_state_per_scenario(df):
    """시나리오별 마지막 측정의 상태 추출."""
    final_df = (
        df.sort_values(["scenario_id", "timestamp"])
        .groupby("scenario_id")
        .tail(1)[["scenario_id", "state"]]
        .rename(columns={"state": "final_state"})
        .reset_index(drop=True)
    )
    return final_df
