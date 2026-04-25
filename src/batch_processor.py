"""
batch_processor.py — 정기 네트워크 점검 배치 모듈

통신사의 정기 네트워크 상태 점검(Periodic Health Check) 프로세스를 모사한다.
실제 통신사에서는 OSS/BSS 시스템과 연동하지만, 여기서는 pandas로 구현.

배치 작업 목록:
  1. 일일 KPI 집계 (Daily KPI Summary)
     - 셀별 측정 유형별 KPI 집계
     - 평균/최대/최소 지연시간, 패킷손실 등
  2. SLA 위반 점검 (SLA Violation Check)
     - 지연시간 20ms 초과, 패킷 손실 3% 초과 식별
     - NOC 보고 대상 자동 추출
  3. 장애 에스컬레이션 후보 (Escalation Candidates)
     - 이상 탐지 결과 기반 NOC 보고 후보 생성
     - 우선순위(URGENT/HIGH/MEDIUM/LOW) 부여
  4. 기지국-코어 정합성 검증 (Reconciliation)
     - 측정 로그 ↔ 집계 데이터 건수/값 교차 검증

실행 시점: main.py 파이프라인의 이상탐지 완료 후
"""

from datetime import datetime

import pandas as pd

# ================================================================
# 배치 설정
# ================================================================
SLA_LATENCY_LIMIT = 20.0        # SLA 지연시간 한계 (ms)
SLA_PACKET_LOSS_LIMIT = 3.0     # SLA 패킷 손실 한계 (%)
NOC_REPORT_THRESHOLD = 1000.0   # NOC 보고 기준 (누적 지연 ms)
ESCALATION_ANOMALY_THRESHOLD = 3  # 에스컬레이션 기준: 시나리오 내 이상 탐지 3건 이상


def run_daily_kpi_summary(df):
    """
    일일 KPI 집계 배치: 셀별 측정 유형별 KPI 집계.

    실제 통신사에서는 이 결과로:
    - 셀별 성능 리포트 생성
    - SLA 준수율 산출
    - 용량 계획(Capacity Planning) 기초 데이터 생성

    Returns:
        pd.DataFrame: 셀별 측정 유형별 건수/KPI 집계
    """
    summary_records = []

    for scenario_id, scenario_group in df.groupby("scenario_id"):
        for cell_id, cell_group in scenario_group.groupby("cell_id"):
            record = {
                "scenario_id": scenario_id,
                "cell_id": cell_id,
                "summary_date": _extract_summary_date(cell_group),
                "total_measurement_count": len(cell_group),
            }

            # 측정 유형별 집계
            if "measurement_type" in cell_group.columns:
                for mtype in ["VOICE", "DATA", "VIDEO", "IOT"]:
                    type_mask = cell_group["measurement_type"] == mtype
                    record[f"{mtype.lower()}_count"] = int(type_mask.sum())
                    record[f"{mtype.lower()}_avg_latency"] = round(
                        cell_group.loc[type_mask, "latency_ms"].mean(), 2
                    ) if type_mask.sum() > 0 else 0.0
            else:
                for mtype in ["voice", "data", "video", "iot"]:
                    record[f"{mtype}_count"] = 0
                    record[f"{mtype}_avg_latency"] = 0.0

            record["total_avg_latency"] = round(cell_group["latency_ms"].mean(), 2)
            record["avg_packet_loss"] = round(cell_group["packet_loss_pct"].mean(), 2)
            record["max_latency"] = round(cell_group["latency_ms"].max(), 2)
            record["min_latency"] = round(cell_group["latency_ms"].min(), 2)

            # SLA 위반 건수
            sla_violations = (cell_group["latency_ms"] > SLA_LATENCY_LIMIT).sum()
            record["sla_violation_count"] = int(sla_violations)

            summary_records.append(record)

    return pd.DataFrame(summary_records)


def run_sla_violation_check(summary_df):
    """
    SLA 위반 점검 배치: SLA 기준 초과 셀 식별.

    5G SLA 기준:
    - E2E Latency ≤ 20ms (eMBB)
    - Packet Loss ≤ 3%

    Returns:
        pd.DataFrame: SLA 위반 셀 목록
    """
    violation_records = []

    for _, row in summary_df.iterrows():
        latency_exceeded = row["max_latency"] > SLA_LATENCY_LIMIT
        loss_exceeded = row["avg_packet_loss"] > SLA_PACKET_LOSS_LIMIT
        noc_report = row["total_avg_latency"] * row["total_measurement_count"] > NOC_REPORT_THRESHOLD

        if latency_exceeded or loss_exceeded or noc_report:
            violation_records.append({
                "scenario_id": row["scenario_id"],
                "cell_id": row["cell_id"],
                "max_latency": row["max_latency"],
                "avg_packet_loss": row["avg_packet_loss"],
                "sla_latency_limit": SLA_LATENCY_LIMIT,
                "latency_exceeded": latency_exceeded,
                "loss_exceeded": loss_exceeded,
                "noc_report_target": noc_report,
                "check_status": "ALERT" if latency_exceeded else "SLA_REVIEW",
            })

    if not violation_records:
        return pd.DataFrame(columns=[
            "scenario_id", "cell_id", "max_latency", "avg_packet_loss",
            "sla_latency_limit", "latency_exceeded", "loss_exceeded",
            "noc_report_target", "check_status"
        ])

    return pd.DataFrame(violation_records)


def run_escalation_candidate_extraction(df, judge_df):
    """
    장애 에스컬레이션 후보 추출 배치: NOC 보고 대상 사전 필터링.

    에스컬레이션 후보 선정 기준:
    1. 시나리오 내 이상 탐지 건수 ≥ ESCALATION_ANOMALY_THRESHOLD
    2. 최종 판정이 FAIL인 시나리오
    3. 복합 장애 패턴 (다중 규칙 동시 위반)

    Returns:
        pd.DataFrame: 에스컬레이션 후보 목록 (우선순위 포함)
    """
    escalation_candidates = []

    anomaly_by_scenario = (
        df[df["anomaly_flag"] == 1]
        .groupby("scenario_id")
        .agg(
            anomaly_count=("anomaly_flag", "sum"),
            unique_reasons=("anomaly_reason", lambda x: len(set("|".join(x).split("|")) - {"normal"})),
            affected_cells=("cell_id", "nunique"),
        )
        .reset_index()
    )

    for _, row in anomaly_by_scenario.iterrows():
        sid = row["scenario_id"]

        judge_row = judge_df[judge_df["scenario_id"] == sid]
        final_result = judge_row["final_result"].values[0] if len(judge_row) > 0 else "UNKNOWN"
        action = judge_row["recommended_action_actual"].values[0] if len(judge_row) > 0 else "UNKNOWN"

        is_escalation_candidate = (
            row["anomaly_count"] >= ESCALATION_ANOMALY_THRESHOLD
            or final_result == "FAIL"
        )

        if not is_escalation_candidate:
            continue

        # 우선순위 산정
        priority_score = 0
        if final_result == "FAIL":
            priority_score += 50
        if row["unique_reasons"] >= 3:
            priority_score += 30
        if row["affected_cells"] >= 3:
            priority_score += 20
        priority_score += min(row["anomaly_count"], 50)

        if priority_score >= 80:
            priority = "URGENT"
        elif priority_score >= 50:
            priority = "HIGH"
        elif priority_score >= 30:
            priority = "MEDIUM"
        else:
            priority = "LOW"

        escalation_candidates.append({
            "scenario_id": sid,
            "anomaly_count": int(row["anomaly_count"]),
            "unique_rule_violations": int(row["unique_reasons"]),
            "affected_cells": int(row["affected_cells"]),
            "final_result": final_result,
            "recommended_action": action,
            "priority_score": priority_score,
            "priority": priority,
            "escalation_status": "PENDING_REVIEW",
            "response_deadline": "T+2시간",
        })

    if not escalation_candidates:
        return pd.DataFrame(columns=[
            "scenario_id", "anomaly_count", "unique_rule_violations",
            "affected_cells", "final_result", "recommended_action",
            "priority_score", "priority", "escalation_status", "response_deadline"
        ])

    return pd.DataFrame(escalation_candidates).sort_values("priority_score", ascending=False).reset_index(drop=True)


def run_reconciliation(df, summary_df):
    """
    기지국-코어 정합성 검증 배치: 측정 로그와 집계 데이터 교차 검증.

    실제 통신사에서는:
    - RAN 측정 로그 ↔ OSS 집계 ↔ 코어망 통계 3자 대사
    - 불일치 시 자동 알림 → 수동 조사

    Returns:
        pd.DataFrame: 시나리오별 정합성 검증 결과
    """
    recon_records = []

    for scenario_id in df["scenario_id"].unique():
        raw_group = df[df["scenario_id"] == scenario_id]
        summary_group = summary_df[summary_df["scenario_id"] == scenario_id]

        raw_total_count = len(raw_group)
        raw_total_latency = round(raw_group["latency_ms"].sum(), 2)

        summary_total_count = int(summary_group["total_measurement_count"].sum()) if len(summary_group) > 0 else 0
        summary_total_latency = round(
            (summary_group["total_avg_latency"] * summary_group["total_measurement_count"]).sum(), 2
        ) if len(summary_group) > 0 else 0

        count_match = raw_total_count == summary_total_count
        latency_diff = abs(raw_total_latency - summary_total_latency)
        latency_match = latency_diff < 1.0  # avg*count 복원 시 부동소수점 누적 오차 허용

        recon_records.append({
            "scenario_id": scenario_id,
            "raw_measurement_count": raw_total_count,
            "summary_measurement_count": summary_total_count,
            "count_match": count_match,
            "raw_total_latency": raw_total_latency,
            "summary_total_latency": summary_total_latency,
            "latency_difference": round(latency_diff, 4),
            "latency_match": latency_match,
            "recon_status": "PASS" if (count_match and latency_match) else "MISMATCH",
        })

    return pd.DataFrame(recon_records)


def run_all_batches(df, judge_df):
    """
    전체 정기점검 배치 실행. main.py에서 호출.

    Returns:
        dict: {
            "kpi_summary": pd.DataFrame,
            "sla_violations": pd.DataFrame,
            "escalation_candidates": pd.DataFrame,
            "reconciliation": pd.DataFrame,
            "batch_summary": dict
        }
    """
    # 1. 일일 KPI 집계
    summary_df = run_daily_kpi_summary(df)

    # 2. SLA 위반 점검
    sla_df = run_sla_violation_check(summary_df)

    # 3. 장애 에스컬레이션 후보 추출
    escalation_df = run_escalation_candidate_extraction(df, judge_df)

    # 4. 정합성 검증
    recon_df = run_reconciliation(df, summary_df)

    # 배치 요약
    batch_summary = {
        "batch_run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpi_summary_cells": len(summary_df),
        "sla_latency_alerts": int(sla_df["latency_exceeded"].sum()) if len(sla_df) > 0 else 0,
        "sla_loss_alerts": int(sla_df["loss_exceeded"].sum()) if len(sla_df) > 0 else 0,
        "escalation_candidates": len(escalation_df),
        "escalation_urgent": int((escalation_df["priority"] == "URGENT").sum()) if len(escalation_df) > 0 else 0,
        "recon_pass": int((recon_df["recon_status"] == "PASS").sum()),
        "recon_mismatch": int((recon_df["recon_status"] == "MISMATCH").sum()),
    }

    return {
        "kpi_summary": summary_df,
        "sla_violations": sla_df,
        "escalation_candidates": escalation_df,
        "reconciliation": recon_df,
        "batch_summary": batch_summary,
    }


def _extract_summary_date(group):
    """측정 그룹에서 집계 일자 추출."""
    if "measurement_time" in group.columns:
        return group["measurement_time"].iloc[0][:10]
    return "2025-01-06"
