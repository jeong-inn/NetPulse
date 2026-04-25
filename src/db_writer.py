"""
db_writer.py — PostgreSQL에 네트워크 파이프라인 결과를 저장하는 모듈

환경변수:
    DATABASE_URL: PostgreSQL 연결 문자열
                  예) postgresql://netpulse:netpulse@localhost:5432/netpulse

psycopg2가 없으면 skip.
"""

import os
import pandas as pd

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


def get_connection():
    """DATABASE_URL 환경변수에서 PostgreSQL 연결 생성."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    if not HAS_PSYCOPG2:
        print("[DB] psycopg2 not installed — skipping DB write", flush=True)
        return None
    try:
        conn = psycopg2.connect(url)
        return conn
    except Exception as e:
        print(f"[DB] Connection failed: {e}", flush=True)
        return None


def write_measurement_events(df, conn):
    """분석된 KPI 로그를 measurement_events 테이블에 저장."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE measurement_events RESTART IDENTITY")

    cols = [
        "timestamp", "measurement_time", "measurement_hour",
        "region_id", "cell_id", "sector_id", "scenario_id",
        "measurement_type", "cell_priority", "neighbor_cell_id",
        "latency_ms", "jitter_ms", "packet_loss_pct", "alarm_code", "interference_flag",
        "latency_roll_mean", "latency_roll_std", "latency_diff", "packet_loss_diff",
        "anomaly_flag", "anomaly_reason", "state"
    ]

    available_cols = [c for c in cols if c in df.columns]
    records = df[available_cols].where(df[available_cols].notna(), None).values.tolist()

    insert_sql = f"""
        INSERT INTO measurement_events ({', '.join(available_cols)})
        VALUES ({', '.join(['%s'] * len(available_cols))})
    """
    psycopg2.extras.execute_batch(cur, insert_sql, records, page_size=1000)
    conn.commit()
    print(f"[DB] measurement_events: {len(records)} rows written", flush=True)


def write_scenario_judgements(judge_df, conn):
    """시나리오 판정 결과를 scenario_judgements 테이블에 저장."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE scenario_judgements")

    records = []
    for _, row in judge_df.iterrows():
        records.append((
            row["scenario_id"], int(row["total_count"]),
            int(row["fail_count"]), int(row["critical_count"]), int(row["warning_count"]),
            float(row["fail_ratio"]), float(row["critical_ratio"]), float(row["warning_ratio"]),
            row["final_result"], row["final_reason"], row["recommended_action_actual"]
        ))

    psycopg2.extras.execute_batch(cur, """
        INSERT INTO scenario_judgements
        (scenario_id, total_count, fail_count, critical_count, warning_count,
         fail_ratio, critical_ratio, warning_ratio, final_result, final_reason, recommended_action)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, records)
    conn.commit()
    print(f"[DB] scenario_judgements: {len(records)} rows written", flush=True)


def write_validation_results(validation_df, conn):
    """검증 결과를 validation_results 테이블에 저장."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE validation_results")

    records = []
    for _, row in validation_df.iterrows():
        records.append((
            row["scenario_id"], row["description"],
            row["expected_final_result"], row["actual_final_result"],
            row["expected_action"], row["actual_action"], int(row["action_gap"]),
            bool(row["result_match"]), bool(row["action_match"]),
            bool(row["keyword_match"]), bool(row["ratio_match"]),
            int(row["validation_score"]), bool(row["overall_match"]),
            row["release_gate"]
        ))

    psycopg2.extras.execute_batch(cur, """
        INSERT INTO validation_results
        (scenario_id, description, expected_final_result, actual_final_result,
         expected_action, actual_action, action_gap,
         result_match, action_match, keyword_match, ratio_match,
         validation_score, overall_match, release_gate)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, records)
    conn.commit()
    print(f"[DB] validation_results: {len(records)} rows written", flush=True)


def write_spc_analysis(spc_df, conn):
    """서비스 품질(SPC) 분석 결과를 spc_analysis 테이블에 저장."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE spc_analysis RESTART IDENTITY")

    records = []
    for _, row in spc_df.iterrows():
        records.append((
            row["scenario_id"], row["param"],
            float(row["cpk"]), float(row["ppk"]),
            float(row["mean"]), float(row["sigma"]),
            float(row["ucl"]), float(row["lcl"]),
            int(row["rule1_count"]), int(row["ooc_count"])
        ))

    psycopg2.extras.execute_batch(cur, """
        INSERT INTO spc_analysis
        (scenario_id, param, cpk, ppk, mean, sigma, ucl, lcl, rule1_count, ooc_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, records)
    conn.commit()
    print(f"[DB] spc_analysis: {len(records)} rows written", flush=True)


def write_root_cause(root_cause_df, conn):
    """원인 분석 결과를 root_cause_analysis 테이블에 저장."""
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE root_cause_analysis")

    records = []
    for _, row in root_cause_df.iterrows():
        records.append((
            row["scenario_id"], row["primary_cause"],
            row["secondary_signal"], row["confidence"], row["evidence"]
        ))

    psycopg2.extras.execute_batch(cur, """
        INSERT INTO root_cause_analysis
        (scenario_id, primary_cause, secondary_signal, confidence, evidence)
        VALUES (%s, %s, %s, %s, %s)
    """, records)
    conn.commit()
    print(f"[DB] root_cause_analysis: {len(records)} rows written", flush=True)


def write_batch_results(batch_result, conn):
    """정기점검 배치 결과를 저장."""
    cur = conn.cursor()

    # KPI 집계
    if len(batch_result.get("kpi_summary", [])) > 0:
        cur.execute("TRUNCATE TABLE batch_kpi_summary RESTART IDENTITY")
        summary_df = batch_result["kpi_summary"]
        records = []
        for _, row in summary_df.iterrows():
            records.append((
                row["scenario_id"], row["cell_id"], row.get("summary_date"),
                int(row["total_measurement_count"]),
                int(row.get("voice_count", 0)), float(row.get("voice_avg_latency", 0)),
                int(row.get("data_count", 0)), float(row.get("data_avg_latency", 0)),
                int(row.get("video_count", 0)), float(row.get("video_avg_latency", 0)),
                int(row.get("iot_count", 0)), float(row.get("iot_avg_latency", 0)),
                float(row["total_avg_latency"]), float(row.get("avg_packet_loss", 0)),
                float(row["max_latency"]), float(row["min_latency"]),
                int(row.get("sla_violation_count", 0))
            ))
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO batch_kpi_summary
            (scenario_id, cell_id, summary_date, total_measurement_count,
             voice_count, voice_avg_latency, data_count, data_avg_latency,
             video_count, video_avg_latency, iot_count, iot_avg_latency,
             total_avg_latency, avg_packet_loss, max_latency, min_latency,
             sla_violation_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, records)
        print(f"[DB] batch_kpi_summary: {len(records)} rows written", flush=True)

    # 에스컬레이션 후보
    if len(batch_result.get("escalation_candidates", [])) > 0:
        cur.execute("TRUNCATE TABLE batch_escalation_candidates RESTART IDENTITY")
        esc_df = batch_result["escalation_candidates"]
        records = []
        for _, row in esc_df.iterrows():
            records.append((
                row["scenario_id"], int(row["anomaly_count"]),
                int(row["unique_rule_violations"]), int(row["affected_cells"]),
                row["final_result"], row["recommended_action"],
                int(row["priority_score"]), row["priority"],
                row["escalation_status"], row["response_deadline"]
            ))
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO batch_escalation_candidates
            (scenario_id, anomaly_count, unique_rule_violations, affected_cells,
             final_result, recommended_action, priority_score, priority,
             escalation_status, response_deadline)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, records)
        print(f"[DB] batch_escalation_candidates: {len(records)} rows written", flush=True)

    # DQ 평가
    if "dq_summary" in batch_result and len(batch_result["dq_summary"]) > 0:
        cur.execute("TRUNCATE TABLE dq_assessment RESTART IDENTITY")
        dq_df = batch_result["dq_summary"]
        records = []
        for _, row in dq_df.iterrows():
            records.append((row["dimension"], float(row["score"]), row["grade"]))
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO dq_assessment (dimension, score, grade)
            VALUES (%s, %s, %s)
        """, records)
        print(f"[DB] dq_assessment: {len(records)} rows written", flush=True)

    conn.commit()


def write_all(df, judge_df, validation_df, spc_df, root_cause_df,
              batch_result=None, dq_result=None):
    """전체 파이프라인 결과를 PostgreSQL에 저장. DB 연결 실패 시 skip."""
    conn = get_connection()
    if conn is None:
        print("[DB] No database connection — skipping DB writes", flush=True)
        return False

    try:
        write_measurement_events(df, conn)
        write_scenario_judgements(judge_df, conn)
        write_validation_results(validation_df, conn)
        write_spc_analysis(spc_df, conn)
        write_root_cause(root_cause_df, conn)

        if batch_result:
            combined = dict(batch_result)
            if dq_result and "summary_df" in dq_result:
                combined["dq_summary"] = dq_result["summary_df"]
            write_batch_results(combined, conn)

        print("[DB] All tables written successfully", flush=True)
        return True
    except Exception as e:
        print(f"[DB] Write failed: {e}", flush=True)
        conn.rollback()
        return False
    finally:
        conn.close()
