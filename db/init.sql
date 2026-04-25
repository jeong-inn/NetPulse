-- NetPulse PostgreSQL Schema
-- 5G 기지국 장애 탐지 파이프라인 결과 저장
-- 3GPP TS 32.425 성능 측정 참조

-- ============================================================
-- 1. 원본 측정 로그 + 분석 결과 (row-level)
-- ============================================================
CREATE TABLE IF NOT EXISTS measurement_events (
    id                  SERIAL PRIMARY KEY,
    timestamp           INTEGER NOT NULL,
    measurement_time    TIMESTAMP,
    measurement_hour    SMALLINT,
    region_id           VARCHAR(30) NOT NULL,
    cell_id             VARCHAR(10) NOT NULL,
    sector_id           VARCHAR(5) NOT NULL,
    scenario_id         VARCHAR(10) NOT NULL,
    -- 측정 정보
    measurement_type    VARCHAR(15),
    cell_priority       SMALLINT DEFAULT 2,
    neighbor_cell_id    VARCHAR(20),
    -- KPI 파라미터
    latency_ms          NUMERIC(12,4) NOT NULL,
    jitter_ms           NUMERIC(10,4) NOT NULL,
    packet_loss_pct     NUMERIC(10,4) NOT NULL,
    alarm_code          INTEGER DEFAULT 0,
    interference_flag   INTEGER DEFAULT 0,
    -- rolling features
    latency_roll_mean       NUMERIC(12,4),
    latency_roll_std        NUMERIC(12,4),
    latency_diff            NUMERIC(12,4),
    packet_loss_diff        NUMERIC(10,4),
    -- 이상 탐지 결과
    anomaly_flag    INTEGER DEFAULT 0,
    anomaly_reason  TEXT DEFAULT 'normal',
    -- 상태 분류
    state           VARCHAR(15) DEFAULT 'GREEN',
    -- 감사 컬럼
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_scenario ON measurement_events(scenario_id);
CREATE INDEX IF NOT EXISTS idx_events_cell ON measurement_events(cell_id);
CREATE INDEX IF NOT EXISTS idx_events_state ON measurement_events(state);
CREATE INDEX IF NOT EXISTS idx_events_anomaly ON measurement_events(anomaly_flag);
CREATE INDEX IF NOT EXISTS idx_events_datetime ON measurement_events(measurement_time);
CREATE INDEX IF NOT EXISTS idx_events_priority ON measurement_events(cell_priority);

-- ============================================================
-- 2. 시나리오별 판정 결과
-- ============================================================
CREATE TABLE IF NOT EXISTS scenario_judgements (
    scenario_id         VARCHAR(10) PRIMARY KEY,
    total_count         INTEGER,
    fail_count          INTEGER,
    critical_count      INTEGER,
    warning_count       INTEGER,
    fail_ratio          NUMERIC(6,3),
    critical_ratio      NUMERIC(6,3),
    warning_ratio       NUMERIC(6,3),
    final_result        VARCHAR(20),
    final_reason        TEXT,
    recommended_action  VARCHAR(30),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. 검증 결과 (expected vs actual)
-- ============================================================
CREATE TABLE IF NOT EXISTS validation_results (
    scenario_id             VARCHAR(10) PRIMARY KEY,
    description             TEXT,
    expected_final_result   VARCHAR(20),
    actual_final_result     VARCHAR(20),
    expected_action         VARCHAR(30),
    actual_action           VARCHAR(30),
    action_gap              INTEGER,
    result_match            BOOLEAN,
    action_match            BOOLEAN,
    keyword_match           BOOLEAN,
    ratio_match             BOOLEAN,
    validation_score        INTEGER,
    overall_match           BOOLEAN,
    release_gate            VARCHAR(20),
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 4. 서비스 품질 분석 (SPC/QoS) 결과
-- ============================================================
CREATE TABLE IF NOT EXISTS spc_analysis (
    id              SERIAL PRIMARY KEY,
    scenario_id     VARCHAR(10) NOT NULL,
    param           VARCHAR(30) NOT NULL,
    cpk             NUMERIC(10,4),
    ppk             NUMERIC(10,4),
    mean            NUMERIC(12,4),
    sigma           NUMERIC(12,4),
    ucl             NUMERIC(12,4),
    lcl             NUMERIC(12,4),
    rule1_count     INTEGER DEFAULT 0,
    ooc_count       INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scenario_id, param)
);

-- ============================================================
-- 5. 원인 분석 결과
-- ============================================================
CREATE TABLE IF NOT EXISTS root_cause_analysis (
    scenario_id      VARCHAR(10) PRIMARY KEY,
    primary_cause    TEXT,
    secondary_signal TEXT,
    confidence       VARCHAR(10),
    evidence         TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 6. 정기점검 — KPI 집계
-- ============================================================
CREATE TABLE IF NOT EXISTS batch_kpi_summary (
    id                      SERIAL PRIMARY KEY,
    scenario_id             VARCHAR(10) NOT NULL,
    cell_id                 VARCHAR(10) NOT NULL,
    summary_date            DATE,
    total_measurement_count INTEGER,
    voice_count             INTEGER DEFAULT 0,
    voice_avg_latency       NUMERIC(12,2) DEFAULT 0,
    data_count              INTEGER DEFAULT 0,
    data_avg_latency        NUMERIC(12,2) DEFAULT 0,
    video_count             INTEGER DEFAULT 0,
    video_avg_latency       NUMERIC(12,2) DEFAULT 0,
    iot_count               INTEGER DEFAULT 0,
    iot_avg_latency         NUMERIC(12,2) DEFAULT 0,
    total_avg_latency       NUMERIC(12,2),
    avg_packet_loss         NUMERIC(12,2),
    max_latency             NUMERIC(12,4),
    min_latency             NUMERIC(12,4),
    sla_violation_count     INTEGER DEFAULT 0,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scenario_id, cell_id)
);

-- ============================================================
-- 7. 정기점검 — 에스컬레이션 후보
-- ============================================================
CREATE TABLE IF NOT EXISTS batch_escalation_candidates (
    id                      SERIAL PRIMARY KEY,
    scenario_id             VARCHAR(10) NOT NULL,
    anomaly_count           INTEGER,
    unique_rule_violations  INTEGER,
    affected_cells          INTEGER,
    final_result            VARCHAR(20),
    recommended_action      VARCHAR(30),
    priority_score          INTEGER,
    priority                VARCHAR(10),
    escalation_status       VARCHAR(20) DEFAULT 'PENDING_REVIEW',
    response_deadline       VARCHAR(20),
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 8. 데이터 품질 평가 (DQM)
-- ============================================================
CREATE TABLE IF NOT EXISTS dq_assessment (
    id          SERIAL PRIMARY KEY,
    dimension   VARCHAR(20) NOT NULL,
    score       NUMERIC(6,2),
    grade       VARCHAR(1),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- SQL 분석 뷰
-- ============================================================

-- 시나리오별 이상 탐지 비율 집계
CREATE OR REPLACE VIEW v_anomaly_ratio_by_scenario AS
SELECT
    scenario_id,
    COUNT(*) AS total_count,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_count,
    ROUND(AVG(anomaly_flag)::numeric, 4) AS anomaly_ratio
FROM measurement_events
GROUP BY scenario_id
ORDER BY anomaly_ratio DESC;

-- 셀별 이상 탐지 집중도
CREATE OR REPLACE VIEW v_anomaly_by_cell AS
SELECT
    scenario_id,
    cell_id,
    COUNT(*) AS total_measurements,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_count,
    ROUND(AVG(anomaly_flag)::numeric, 4) AS anomaly_ratio,
    ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency,
    MAX(latency_ms) AS max_latency
FROM measurement_events
GROUP BY scenario_id, cell_id
ORDER BY scenario_id, anomaly_ratio DESC;

-- 섹터별 장애 분포
CREATE OR REPLACE VIEW v_sector_health AS
SELECT
    scenario_id,
    sector_id,
    COUNT(*) FILTER (WHERE anomaly_reason LIKE '%measurement_loss%') AS loss_count,
    COUNT(*) FILTER (WHERE anomaly_reason LIKE '%alarm_detected%') AS alarm_count,
    COUNT(*) FILTER (WHERE anomaly_reason LIKE '%interference_event%') AS interference_count,
    ROUND(AVG(jitter_ms)::numeric, 2) AS avg_jitter,
    ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency
FROM measurement_events
GROUP BY scenario_id, sector_id
ORDER BY scenario_id, sector_id;

-- YELLOW 이상 상태가 3건 연속된 구간 탐지 (window function)
CREATE OR REPLACE VIEW v_consecutive_warning_streaks AS
SELECT scenario_id, cell_id, state, streak_length, streak_start
FROM (
    SELECT
        scenario_id,
        cell_id,
        state,
        COUNT(*) OVER (PARTITION BY scenario_id, grp) AS streak_length,
        MIN(timestamp) OVER (PARTITION BY scenario_id, grp) AS streak_start,
        ROW_NUMBER() OVER (PARTITION BY scenario_id, grp ORDER BY timestamp) AS rn
    FROM (
        SELECT *,
            SUM(CASE WHEN state != LAG(state) OVER (PARTITION BY scenario_id ORDER BY timestamp)
                     THEN 1 ELSE 0 END)
            OVER (PARTITION BY scenario_id ORDER BY timestamp) AS grp
        FROM measurement_events
    ) grouped
    WHERE state IN ('YELLOW', 'RED', 'BLACKOUT')
) streaks
WHERE rn = 1 AND streak_length >= 3
ORDER BY scenario_id, streak_start;

-- 서비스 품질 능력 요약 (Cpk < 1.33 = SLA 미달)
CREATE OR REPLACE VIEW v_spc_risk_summary AS
SELECT
    scenario_id,
    param,
    cpk,
    ppk,
    rule1_count,
    ooc_count,
    CASE
        WHEN cpk >= 1.33 THEN 'CAPABLE'
        WHEN cpk >= 1.00 THEN 'MARGINAL'
        ELSE 'INCAPABLE'
    END AS capability_status
FROM spc_analysis
ORDER BY cpk ASC;

-- 릴리즈 게이트 현황 대시보드
CREATE OR REPLACE VIEW v_release_gate_dashboard AS
SELECT
    v.scenario_id,
    v.actual_final_result AS result,
    v.validation_score,
    v.release_gate,
    v.overall_match,
    j.recommended_action,
    j.warning_ratio,
    j.critical_ratio
FROM validation_results v
JOIN scenario_judgements j ON v.scenario_id = j.scenario_id
ORDER BY
    CASE v.release_gate
        WHEN 'BLOCKED' THEN 1
        WHEN 'REVIEW_REQUIRED' THEN 2
        WHEN 'MONITORING_REQUIRED' THEN 3
        WHEN 'READY' THEN 4
    END;

-- 측정 유형별 이상 탐지 분포
CREATE OR REPLACE VIEW v_anomaly_by_measurement_type AS
SELECT
    scenario_id,
    measurement_type,
    COUNT(*) AS total_measurements,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_count,
    ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency,
    ROUND(AVG(CASE WHEN anomaly_flag = 1 THEN latency_ms END)::numeric, 2) AS avg_anomaly_latency
FROM measurement_events
WHERE measurement_type IS NOT NULL
GROUP BY scenario_id, measurement_type
ORDER BY scenario_id, measurement_type;

-- 핵심 셀(중요도 4~5) 모니터링
CREATE OR REPLACE VIEW v_high_priority_cell_activity AS
SELECT
    scenario_id,
    cell_id,
    cell_priority,
    COUNT(*) AS measurement_count,
    ROUND(AVG(latency_ms)::numeric, 2) AS avg_latency,
    MAX(latency_ms) AS max_latency,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_count
FROM measurement_events
WHERE cell_priority >= 4
GROUP BY scenario_id, cell_id, cell_priority
ORDER BY cell_priority DESC, anomaly_count DESC;

-- 에스컬레이션 후보 현황
CREATE OR REPLACE VIEW v_escalation_pipeline_status AS
SELECT
    e.scenario_id,
    e.priority,
    e.priority_score,
    e.anomaly_count,
    e.escalation_status,
    e.response_deadline,
    j.final_result,
    j.recommended_action
FROM batch_escalation_candidates e
JOIN scenario_judgements j ON e.scenario_id = j.scenario_id
ORDER BY e.priority_score DESC;
