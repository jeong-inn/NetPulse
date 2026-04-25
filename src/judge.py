"""
judge.py — 시나리오별 최종 판정 엔진

각 시나리오의 전체 상태 흐름을 분석하여 최종 판정(PASS/PASS_WITH_WARNING/FAIL)을
결정하고, NOC 운영 정책(셀셧다운/에스컬레이션/현장출동 등)을 권고한다.

판정 기준:
  PASS             : 모든 KPI 정상 범위 유지
  PASS_WITH_WARNING: 일시적 이상이 있었으나 자가 회복됨
  FAIL             : 지속적/심각한 이상으로 셀 운용 불가 판정

판정 후 policy_engine의 recommend_action_policy()를 호출하여
NOC 에스컬레이션 대상 여부를 판단한다.
"""

import pandas as pd
from policy_engine import recommend_action_policy


def judge_scenarios(df):
    """
    시나리오별 최종 판정을 수행한다.

    로직:
    1. 상태(state) 분포 집계 (BLACKOUT/RED/YELLOW/GREEN/RECOVERING)
    2. BLACKOUT 존재 → 즉시 FAIL 판정
    3. YELLOW 비율 ≥ 40% → FAIL (장시간 이상 지속)
    4. RED 비율 ≥ 2% → FAIL (치명적 이상 반복)
    5. 복합 이상 조합 → FAIL
    6. YELLOW/RED 존재 → PASS_WITH_WARNING
    7. 그 외 → PASS
    """
    results = []

    for scenario_id, group in df.groupby("scenario_id"):
        g = group.sort_values("timestamp").copy()
        total_count = len(g)

        state_counts = g["state"].value_counts().to_dict()

        fail_count = state_counts.get("BLACKOUT", 0)
        critical_count = state_counts.get("RED", 0)
        warning_count = state_counts.get("YELLOW", 0)

        fail_ratio = fail_count / total_count
        critical_ratio = critical_count / total_count
        warning_ratio = warning_count / total_count

        all_reasons = "|".join(g["anomaly_reason"].astype(str).tolist())

        has_measurement_loss = "measurement_loss" in all_reasons
        has_alarm = "alarm_detected" in all_reasons
        has_interference = "interference_event" in all_reasons
        has_loss = ("packet_loss_high" in all_reasons) or ("packet_loss_jump" in all_reasons)
        has_latency = ("latency_high" in all_reasons) or ("latency_spike" in all_reasons)

        # 최종 판정
        if fail_count > 0:
            final_result = "FAIL"

            if has_measurement_loss:
                final_reason = "기지국 측정 신호 손실로 셀 운용 중단 필요"
            elif has_alarm and has_interference:
                final_reason = "복합 장애(장비알람+외부간섭) 발생으로 긴급 복구 필요"
            elif has_loss:
                final_reason = "패킷 손실률 누적 초과로 서비스 품질 기준 미달"
            elif has_latency:
                final_reason = "지연시간 지속 초과로 SLA 위반 — NOC 에스컬레이션 필요"
            else:
                final_reason = "BLACKOUT 상태 발생으로 최종 FAIL 판정"

        elif warning_ratio >= 0.40:
            final_result = "FAIL"

            if has_latency and has_loss:
                final_reason = "지연시간 이상과 패킷 손실이 장시간 지속 — NOC 보고 대상"
            elif has_latency:
                final_reason = "지연시간 이상 상태가 장시간 지속 — 백홀 용량 점검 필요"
            elif has_loss:
                final_reason = "패킷 손실 장시간 지속 — 전송 장비 점검 필요"
            else:
                final_reason = "YELLOW 상태 장시간 지속으로 운영 불가 판정"

        elif critical_ratio >= 0.02:
            final_result = "FAIL"

            if has_alarm and has_interference:
                final_reason = "복합 장애 반복 발생 — 현장 엔지니어 파견 필요"
            else:
                final_reason = "RED 상태 반복 발생으로 최종 FAIL 판정"

        elif (has_latency and has_loss and has_alarm) or (has_latency and has_interference):
            final_result = "FAIL"
            final_reason = "복합 이상 조합 확인 — 다중 KPI 동시 위반"

        elif critical_count > 0 or warning_count > 0:
            final_result = "PASS_WITH_WARNING"

            if critical_count > 0:
                final_reason = "RED 상태가 있었으나 자가 회복 — 강화 모니터링 권고"
            else:
                final_reason = "YELLOW 수준 이상 징후가 있었으나 자가 회복 — 추이 관찰 필요"

        else:
            final_result = "PASS"
            final_reason = "정상 범위 유지 — 별도 조치 불필요"

        # 대응 정책 결정
        recommended_action_actual = recommend_action_policy(
            final_result=final_result,
            has_measurement_loss=has_measurement_loss,
            has_alarm=has_alarm,
            has_interference=has_interference,
            has_loss=has_loss,
            has_latency=has_latency,
            warning_ratio=warning_ratio,
            critical_ratio=critical_ratio,
            fail_ratio=fail_ratio
        )

        results.append({
            "scenario_id": scenario_id,
            "total_count": total_count,
            "fail_count": fail_count,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "fail_ratio": round(fail_ratio, 3),
            "critical_ratio": round(critical_ratio, 3),
            "warning_ratio": round(warning_ratio, 3),
            "final_result": final_result,
            "final_reason": final_reason,
            "recommended_action_actual": recommended_action_actual,
            "all_reasons": all_reasons
        })

    return pd.DataFrame(results).sort_values("scenario_id").reset_index(drop=True)
