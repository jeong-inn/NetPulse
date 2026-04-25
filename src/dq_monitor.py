"""
dq_monitor.py — 측정 데이터 품질 관리(DQM) 모듈

네트워크 측정 데이터 품질 관리 4차원 검증을 수행한다.
3GPP TS 32.401 성능 관리 및 통신사 데이터 거버넌스 가이드라인 기반.

4차원 품질 검증 체계:
  1. 완전성 (Completeness)  — 필수 KPI 컬럼 결측치 검사
  2. 정합성 (Consistency)   — 컬럼 간 논리적 일관성 검증
  3. 적시성 (Timeliness)    — 측정 데이터 수집 지연 여부 검사
  4. 정확성 (Accuracy)      — 값 범위/포맷 유효성 검증

등급 체계:
  A (≥ 95%): 우수 — 정상 운영
  B (≥ 85%): 양호 — 모니터링 필요
  C (≥ 70%): 미흡 — 개선 조치 필요
  D (< 70%): 부적합 — 즉시 시정 필요

DQM은 네트워크 KPI 리포트 및 규제 보고(MSIT, 방통위) 데이터의 신뢰성을 담보하는 필수 프로세스.
"""

import pandas as pd
import numpy as np


# ================================================================
# DQM 설정
# ================================================================

# 필수 컬럼 목록 (결측 불허)
REQUIRED_COLUMNS = [
    "timestamp", "region_id", "cell_id", "sector_id",
    "scenario_id", "latency_ms", "jitter_ms",
    "packet_loss_pct", "alarm_code", "interference_flag",
]

# 값 범위 규격 (정확성 검증용)
VALUE_SPECS = {
    "latency_ms": {"min": 0, "max": 10000},            # 0 ~ 10초
    "jitter_ms": {"min": 0, "max": 1000},               # 0 ~ 1초
    "packet_loss_pct": {"min": 0, "max": 100},           # 0 ~ 100%
    "alarm_code": {"min": 0, "max": 999},                # 3자리 코드
    "interference_flag": {"allowed": [0, 1]},             # 이진값
}

# 적시성 기준
TIMELINESS_THRESHOLD_MS = 50  # 지연시간 50ms 초과 시 지연 판정


def check_completeness(df):
    """
    완전성 검사: 필수 KPI 컬럼의 결측치(NULL/NaN) 비율을 측정한다.

    3GPP 데이터 품질 기준: 필수 항목 결측률 0% 목표.

    Returns:
        dict: score, total_cells, missing_cells, details
    """
    details = []
    total_cells = 0
    missing_cells = 0

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            n = len(df)
            details.append({
                "column": col,
                "total": n,
                "missing": n,
                "missing_rate": 1.0,
                "status": "COLUMN_MISSING",
            })
            total_cells += n
            missing_cells += n
        else:
            n = len(df)
            n_missing = int(df[col].isna().sum())
            rate = n_missing / n if n > 0 else 0

            details.append({
                "column": col,
                "total": n,
                "missing": n_missing,
                "missing_rate": round(rate, 6),
                "status": "PASS" if n_missing == 0 else "FAIL",
            })
            total_cells += n
            missing_cells += n_missing

    score = ((total_cells - missing_cells) / total_cells * 100) if total_cells > 0 else 0

    return {
        "dimension": "completeness",
        "score": round(score, 2),
        "total_cells": total_cells,
        "missing_cells": missing_cells,
        "details": details,
    }


def check_consistency(df):
    """
    정합성 검사: 컬럼 간 논리적 관계가 성립하는지 검증한다.

    검증 규칙:
    C1. latency_ms > 0 (음수 지연시간 불가)
    C2. jitter_ms = 0 이면 measurement_loss로 분류되어야 함
    C3. measurement_type이 있으면 유효한 값이어야 함
    C4. cell_priority 범위 검증

    Returns:
        dict: 정합성 점수 및 위반 상세
    """
    n = len(df)
    violations = []

    # C1: 음수 지연시간
    neg_latency = (df["latency_ms"] < 0).sum()
    if neg_latency > 0:
        violations.append({
            "rule": "C1_no_negative_latency",
            "violation_count": int(neg_latency),
            "description": "음수 지연시간 존재",
        })

    # C2: jitter measurement loss 일관성
    if "anomaly_reason" in df.columns:
        loss_mask = df["jitter_ms"] <= 0.1
        has_loss_reason = df["anomaly_reason"].str.contains("measurement_loss", na=False)
        inconsistent = loss_mask & ~has_loss_reason & (df.get("anomaly_flag", pd.Series([0]*n)) == 1)
        inconsistent_count = int(inconsistent.sum())
        if inconsistent_count > 0:
            violations.append({
                "rule": "C2_measurement_loss_consistency",
                "violation_count": inconsistent_count,
                "description": "jitter ≤ 0.1ms이나 measurement_loss로 분류되지 않음",
            })

    # C3: measurement_type 유효성
    if "measurement_type" in df.columns:
        valid_types = {"VOICE", "DATA", "VIDEO", "IOT"}
        invalid_type = ~df["measurement_type"].isin(valid_types)
        invalid_count = int(invalid_type.sum())
        if invalid_count > 0:
            violations.append({
                "rule": "C3_valid_measurement_type",
                "violation_count": invalid_count,
                "description": "유효하지 않은 측정 유형 존재",
            })

    # C4: cell_priority 범위
    if "cell_priority" in df.columns:
        invalid_priority = ~df["cell_priority"].isin([1, 2, 3, 4, 5])
        invalid_count = int(invalid_priority.sum())
        if invalid_count > 0:
            violations.append({
                "rule": "C4_valid_cell_priority",
                "violation_count": invalid_count,
                "description": "유효하지 않은 셀 중요도 등급",
            })

    total_checks = n * 4
    total_violations = sum(v["violation_count"] for v in violations)
    score = ((total_checks - total_violations) / total_checks * 100) if total_checks > 0 else 100

    return {
        "dimension": "consistency",
        "score": round(score, 2),
        "total_checks": total_checks,
        "total_violations": total_violations,
        "details": violations,
    }


def check_timeliness(df):
    """
    적시성 검사: 측정 데이터 수집 지연 여부를 측정한다.

    5G 네트워크 기준: E2E 지연 50ms 이내, 지터 10ms 이내.

    Returns:
        dict: 적시성 점수 및 지연 건수
    """
    n = len(df)

    delayed_mask = df["latency_ms"] > TIMELINESS_THRESHOLD_MS
    delayed_count = int(delayed_mask.sum())

    # 지터 기준
    jitter_delayed = (df["jitter_ms"] > 10).sum()

    details = [
        {
            "metric": "latency_delay",
            "threshold_ms": TIMELINESS_THRESHOLD_MS,
            "delayed_count": delayed_count,
            "delayed_rate": round(delayed_count / n, 6) if n > 0 else 0,
        },
        {
            "metric": "jitter_delay",
            "threshold_ms": 10,
            "delayed_count": int(jitter_delayed),
            "delayed_rate": round(int(jitter_delayed) / n, 6) if n > 0 else 0,
        },
    ]

    on_time_count = n - delayed_count
    score = (on_time_count / n * 100) if n > 0 else 100

    return {
        "dimension": "timeliness",
        "score": round(score, 2),
        "total_measurements": n,
        "on_time_count": on_time_count,
        "delayed_count": delayed_count,
        "details": details,
    }


def check_accuracy(df):
    """
    정확성 검사: 값의 범위 및 포맷 유효성을 검증한다.

    각 KPI 컬럼이 정의된 VALUE_SPECS 범위 내에 있는지 확인.

    Returns:
        dict: 정확성 점수 및 범위 이탈 건수
    """
    n = len(df)
    violations = []

    for col, spec in VALUE_SPECS.items():
        if col not in df.columns:
            continue

        if "allowed" in spec:
            invalid = ~df[col].isin(spec["allowed"])
            count = int(invalid.sum())
            if count > 0:
                violations.append({
                    "column": col,
                    "rule": "allowed_values",
                    "violation_count": count,
                    "description": f"{col}: 허용 값 {spec['allowed']} 외 존재",
                })
        else:
            below_min = (df[col] < spec["min"]).sum()
            above_max = (df[col] > spec["max"]).sum()
            count = int(below_min + above_max)
            if count > 0:
                violations.append({
                    "column": col,
                    "rule": "value_range",
                    "violation_count": count,
                    "description": f"{col}: 범위 [{spec['min']}, {spec['max']}] 이탈",
                })

    total_checks = n * len(VALUE_SPECS)
    total_violations = sum(v["violation_count"] for v in violations)
    score = ((total_checks - total_violations) / total_checks * 100) if total_checks > 0 else 100

    return {
        "dimension": "accuracy",
        "score": round(score, 2),
        "total_checks": total_checks,
        "total_violations": total_violations,
        "details": violations,
    }


def _assign_grade(score):
    """DQM 등급 부여."""
    if score >= 95:
        return "A"
    elif score >= 85:
        return "B"
    elif score >= 70:
        return "C"
    else:
        return "D"


def run_dq_assessment(df):
    """
    전체 데이터 품질 평가 실행. main.py에서 호출.

    4차원 검증을 수행하고 종합 점수 및 등급을 산출한다.

    Returns:
        dict: {
            "completeness": dict,
            "consistency": dict,
            "timeliness": dict,
            "accuracy": dict,
            "overall_score": float,
            "overall_grade": str,
            "summary_df": pd.DataFrame
        }
    """
    completeness = check_completeness(df)
    consistency = check_consistency(df)
    timeliness = check_timeliness(df)
    accuracy = check_accuracy(df)

    # 종합 점수 (가중 평균: 완전성 30%, 정합성 25%, 적시성 20%, 정확성 25%)
    overall_score = (
        completeness["score"] * 0.30
        + consistency["score"] * 0.25
        + timeliness["score"] * 0.20
        + accuracy["score"] * 0.25
    )
    overall_score = round(overall_score, 2)
    overall_grade = _assign_grade(overall_score)

    summary_rows = []
    for result in [completeness, consistency, timeliness, accuracy]:
        summary_rows.append({
            "dimension": result["dimension"],
            "score": result["score"],
            "grade": _assign_grade(result["score"]),
        })
    summary_rows.append({
        "dimension": "overall",
        "score": overall_score,
        "grade": overall_grade,
    })

    return {
        "completeness": completeness,
        "consistency": consistency,
        "timeliness": timeliness,
        "accuracy": accuracy,
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "summary_df": pd.DataFrame(summary_rows),
    }
