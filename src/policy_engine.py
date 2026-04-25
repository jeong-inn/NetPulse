"""
policy_engine.py — 네트워크 운영 정책 엔진

통신사 NOC 운영 절차 및 3GPP TS 32.111 알람 관리 가이드라인 기반의
기지국 장애 대응 정책을 결정한다.

대응 액션 체계 (우선순위 순):
  NO_ACTION              : 정상 — 별도 조치 불필요
  ENHANCED_MONITORING    : 강화모니터링 — KPI 추이 지속 관찰
  PARAMETER_OPTIMIZATION : 파라미터 최적화 — 안테나 틸트/파워 자동 조정
  FIELD_INSPECTION       : 현장 점검 — 기지국 현장 엔지니어 파견
  NOC_ESCALATION         : NOC 에스컬레이션 — 네트워크운영센터 보고
  CELL_SHUTDOWN          : 셀 셧다운 — 장애 셀 운용 중단 및 인접 셀 트래픽 전환
  EMERGENCY_HALT         : 긴급 중단 — 광역 장애 시 전면 중단 및 복구팀 출동

릴리즈 게이트 (배포/변경 관리):
  READY                : 정상 운영
  MONITORING_REQUIRED  : 운영 가능, 모니터링 필요
  REVIEW_REQUIRED      : 변경 보류, 검토 필요
  BLOCKED              : 변경 차단
"""

import pandas as pd

# 대응 액션 우선순위 (높을수록 긴급)
ACTION_PRIORITY = {
    "NO_ACTION": 0,
    "ENHANCED_MONITORING": 1,
    "PARAMETER_OPTIMIZATION": 2,
    "FIELD_INSPECTION": 3,
    "NOC_ESCALATION": 4,
    "CELL_SHUTDOWN": 5,
    "EMERGENCY_HALT": 6,
}


def recommend_action_policy(final_result, has_measurement_loss, has_alarm, has_interference,
                            has_loss, has_latency,
                            warning_ratio, critical_ratio, fail_ratio):
    """
    최종 판정 결과와 탐지 이벤트 조합을 바탕으로 대응 액션을 결정한다.

    NOC 장애 대응 절차:
    1. 측정 신호 손실 → 즉시 셀 셧다운 + 인접 셀 전환
    2. 복합 장애(알람+간섭) → 긴급 중단 에스컬레이션
    3. FAIL 판정 → 심각도에 따라 NOC 에스컬레이션 ~ 긴급 중단
    4. WARNING 판정 → 모니터링 ~ 파라미터 최적화
    """
    if has_measurement_loss:
        return "CELL_SHUTDOWN"

    if final_result == "FAIL":
        if has_alarm and has_interference:
            return "EMERGENCY_HALT"
        if fail_ratio >= 0.05 and has_loss:
            return "EMERGENCY_HALT"
        if critical_ratio >= 0.10:
            return "EMERGENCY_HALT"
        if has_latency and has_loss:
            return "NOC_ESCALATION"
        if has_loss:
            return "FIELD_INSPECTION"
        if has_latency:
            return "NOC_ESCALATION"
        return "NOC_ESCALATION"

    if final_result == "PASS_WITH_WARNING":
        if critical_ratio > 0:
            return "PARAMETER_OPTIMIZATION"
        if warning_ratio >= 0.03:
            return "ENHANCED_MONITORING"
        return "NO_ACTION"

    return "NO_ACTION"


def action_gap(expected_action, actual_action):
    """대응 액션 간 우선순위 차이. 양수 = 과잉대응, 음수 = 과소대응."""
    e = ACTION_PRIORITY.get(expected_action, 0)
    a = ACTION_PRIORITY.get(actual_action, 0)
    return a - e


def decide_gate(final_result, overall_match, warning_ratio, critical_ratio, fail_ratio):
    """
    릴리즈 게이트 판정.
    통신사 네트워크 변경 관리 프로세스의 승인 게이트를 모사.
    """
    if final_result == "FAIL":
        return "BLOCKED"

    if not overall_match:
        return "REVIEW_REQUIRED"

    if critical_ratio > 0 or fail_ratio > 0:
        return "REVIEW_REQUIRED"

    if warning_ratio >= 0.03:
        return "MONITORING_REQUIRED"

    return "READY"


def summarize_quality(validation_df):
    """전체 시나리오 품질 요약 (운영 대시보드용)."""
    total = len(validation_df)
    match_count = int(validation_df["overall_match"].sum())
    mismatch_count = total - match_count
    match_rate = round(match_count / total, 3) if total > 0 else 0.0

    gate_counts = validation_df["release_gate"].value_counts().to_dict()

    return pd.DataFrame([{
        "scenario_total": total,
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "match_rate": match_rate,
        "ready_count": gate_counts.get("READY", 0),
        "monitoring_required_count": gate_counts.get("MONITORING_REQUIRED", 0),
        "review_required_count": gate_counts.get("REVIEW_REQUIRED", 0),
        "blocked_count": gate_counts.get("BLOCKED", 0),
    }])
