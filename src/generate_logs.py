"""
generate_logs.py — 5G 기지국 네트워크 KPI 시뮬레이션 로그 생성

NOC(Network Operations Center) 장애 탐지 검증용 합성 기지국 KPI 로그를 생성한다.
3GPP TS 32.425 성능 측정 항목 및 LG U+ NOC 운영 가이드라인을 참고하되,
np.random.seed(42)로 결과 재현성을 보장한다.

구조:
  1 Region × 5 Cells(gNB) × 8 Sectors × 25 measurements = 1,000 rows/scenario
  10 scenarios × 1,000 = 총 10,000 rows

KPI 파라미터:
  latency_ms          : E2E 네트워크 지연시간 (ms), 5G eMBB 기준 10ms 이내
  jitter_ms           : 네트워크 지터 (ms), 실시간 서비스 기준 3ms 이내
  packet_loss_pct     : 패킷 손실률 (%), 정상 운영 기준 1% 미만
  alarm_code          : 장비 알람 코드 (0=정상)
  interference_flag   : 외부 간섭 플래그 (0/1)

부가 정보:
  measurement_time    : 측정 일시 (ISO 8601)
  measurement_hour    : 측정 시각 (0~23)
  measurement_type    : 측정 유형 (VOICE/DATA/VIDEO/IOT)
  cell_priority       : 셀 중요도 등급 (1=LOW ~ 5=CRITICAL, 트래픽 밀집도 기반)
  neighbor_cell_id    : 인접 셀 ID (DATA 유형 핸드오버 시)

⚠️ 주의: seed=42 고정. 이 파일을 수정하면 전체 synthetic 결과가 변경됨.
"""

import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

np.random.seed(42)

# 구조 상수
N_CELLS = 5
N_SECTORS = 8
N_MEASUREMENTS = 25  # 셀당 섹터당 측정 수
REGION_ID = "REGION_SEOUL_001"

# 측정 유형 분포 (5G 트래픽 비율 기반)
MEASUREMENT_TYPES = ["VOICE", "DATA", "VIDEO", "IOT"]
MEASUREMENT_TYPE_PROBS = [0.15, 0.40, 0.30, 0.15]

# 셀 중요도 등급 분포 (트래픽 밀집도/중요시설 기반)
PRIORITY_LEVELS = [1, 2, 3, 4, 5]  # 1=LOW, 2=NORMAL, 3=MEDIUM, 4=HIGH, 5=CRITICAL
PRIORITY_PROBS = [0.30, 0.40, 0.20, 0.08, 0.02]

# 측정 시작 기준일
BASE_DATETIME = datetime(2025, 1, 6, 0, 0, 0)  # 월요일 00시 (24시간 모니터링)


def _make_index():
    """
    Region-Cell-Sector-측정 순서로 인덱스 생성 (1,000 rows).
    각 row에 측정 일시, 유형, 셀 중요도 등 부가 정보를 부여.
    """
    records = []
    t = 0
    for c in range(1, N_CELLS + 1):
        for s in range(1, N_SECTORS + 1):
            for m in range(N_MEASUREMENTS):
                # 측정 일시: 5분 간격 (24시간 연속 모니터링)
                meas_dt = BASE_DATETIME + timedelta(minutes=t * 5)
                meas_type = np.random.choice(MEASUREMENT_TYPES, p=MEASUREMENT_TYPE_PROBS)
                priority = int(np.random.choice(PRIORITY_LEVELS, p=PRIORITY_PROBS))

                neighbor = ""
                if meas_type == "DATA":
                    neighbor = f"NB_{np.random.randint(1000, 9999)}"

                records.append({
                    "timestamp": t,
                    "measurement_time": meas_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "measurement_hour": meas_dt.hour,
                    "region_id": REGION_ID,
                    "cell_id": f"CELL{c:02d}",
                    "sector_id": f"SEC{s:01d}",
                    "measurement_type": meas_type,
                    "cell_priority": priority,
                    "neighbor_cell_id": neighbor,
                })
                t += 1
    return pd.DataFrame(records)


def make_base_log(scenario_id="S1"):
    """
    기본 정상 기지국 KPI 로그 생성.
    지연시간은 5G eMBB 기준(10ms) 내 정규분포.
    지터는 실시간 서비스 기준(3ms) 내 정규분포.
    """
    idx = _make_index()
    n = len(idx)  # 1000

    idx["scenario_id"] = scenario_id
    idx["latency_ms"] = 10 + np.random.normal(0, 1.5, n)
    idx["jitter_ms"] = 3.0 + np.random.normal(0, 0.5, n)
    idx["packet_loss_pct"] = 1.0 + np.random.normal(0, 0.3, n)
    idx["alarm_code"] = 0
    idx["interference_flag"] = 0

    return idx.reset_index(drop=True)


# ================================================================
# 이상 주입 함수 (Anomaly Injection)
# ================================================================

def _cell_mask(df, cell_from=1, cell_to=None):
    """특정 cell 범위에 해당하는 row mask 반환"""
    cell_nums = df["cell_id"].str.extract(r"CELL(\d+)")[0].astype(int)
    if cell_to is None:
        cell_to = N_CELLS
    return (cell_nums >= cell_from) & (cell_nums <= cell_to)


def _sector_mask(df, sector_ids):
    """특정 sector 번호 리스트에 해당하는 row mask 반환"""
    return df["sector_id"].isin([f"SEC{s}" for s in sector_ids])


def inject_latency_spike(df, start=300, end=340, magnitude=10):
    """네트워크 지연시간 일시적 스파이크 주입 (백홀 순간 과부하)"""
    df = df.copy()
    df.loc[start:end, "latency_ms"] += magnitude
    return df


def inject_latency_drift(df, cell_from=3, slope=0.005):
    """
    특정 셀 이후 latency_ms 점진 상승.
    백홀 용량 부족 패턴: 트래픽 증가에 따른 점진적 지연 악화.
    """
    df = df.copy()
    mask = _cell_mask(df, cell_from=cell_from)
    drift_idx = df.index[mask]
    drift_vals = np.arange(len(drift_idx)) * slope * 40
    df.loc[drift_idx, "latency_ms"] += drift_vals
    return df


def inject_packet_loss_drift(df, cell_from=3, slope=0.015):
    """
    특정 셀 이후 packet_loss_pct 점진 증가.
    장비 노후화 패턴: 전송 장비 열화에 따른 패킷 손실 증가.
    """
    df = df.copy()
    mask = _cell_mask(df, cell_from=cell_from)
    drift_idx = df.index[mask]
    drift_vals = np.arange(len(drift_idx)) * slope
    df.loc[drift_idx, "packet_loss_pct"] += drift_vals
    return df


def inject_alarm_repeat(df, positions):
    """
    특정 위치에 반복 alarm_code 삽입.
    장비 간헐적 고장 패턴.
    """
    df = df.copy()
    for p in positions:
        if 0 <= p < len(df):
            df.loc[p, "alarm_code"] = 21
    return df


def inject_measurement_loss(df, sector_ids, cell_from=2, cell_to=3):
    """
    특정 sector + cell 구간에서 jitter 측정 신호 손실.
    기지국 정전/장비 고장: 측정 프로브 응답 불능 상태.
    """
    df = df.copy()
    mask = _sector_mask(df, sector_ids) & _cell_mask(df, cell_from, cell_to)
    df.loc[mask, "jitter_ms"] = 0
    return df


def inject_traffic_burst(df, start=200, end=260, scale=5):
    """
    대규모 이벤트에 의한 트래픽 burst 주입.
    콘서트/스포츠경기 등 특정 지역 트래픽 급증 패턴.
    """
    df = df.copy()
    noise = np.random.normal(0, scale, end - start + 1)
    df.loc[start:end, "latency_ms"] += noise
    return df


def inject_latency_high_cells(df, cell_from=2, cell_to=5, offset=10):
    """
    특정 셀 범위 전체에서 latency_ms 높은 수준 지속.
    광역 네트워크 장애 패턴: 코어망 또는 백홀 구간 이상.
    """
    df = df.copy()
    mask = _cell_mask(df, cell_from=cell_from, cell_to=cell_to)
    df.loc[mask, "latency_ms"] += offset
    return df


# ================================================================
# 시나리오 빌드 (10개)
# ================================================================

def build_scenarios():
    """
    NOC 장애 탐지 검증용 10개 시나리오를 생성한다.

    S1:  정상 운영 (baseline)
    S2:  지연시간 일시 스파이크 후 자가 회복 (백홀 순간 과부하)
    S3:  지연시간 지속 상승 — 백홀 용량 부족 의심
    S4:  패킷 손실률 점진 증가 — 전송 장비 노후화
    S5:  반복 장비 알람 — 간헐적 하드웨어 고장
    S6:  측정 신호 손실 — 기지국 정전/장비 고장
    S7:  트래픽 burst 후 회복 (대규모 이벤트)
    S8:  복합 장애 — 지연+손실+알람+간섭 동시 발생
    S9:  장애 감지 후 자동 복구 (파라미터 최적화)
    S10: 복합 장애 후 복구 실패 — 현장 출동 필요
    """
    scenarios = []

    # S1: 정상 운영 구간
    s1 = make_base_log("S1")
    scenarios.append(s1)

    # S2: CELL03에서 지연시간 순간 스파이크 후 자가 회복
    s2 = make_base_log("S2")
    s2 = inject_latency_spike(s2, 400, 440, 10)
    scenarios.append(s2)

    # S3: CELL02 이후 지연시간 지속 상승 — 백홀 용량 부족
    s3 = make_base_log("S3")
    s3 = inject_latency_high_cells(s3, cell_from=2, cell_to=5, offset=10)
    scenarios.append(s3)

    # S4: CELL03 이후 패킷 손실 점진 증가 — 전송 장비 노후화
    s4 = make_base_log("S4")
    s4 = inject_packet_loss_drift(s4, cell_from=3, slope=0.015)
    scenarios.append(s4)

    # S5: 반복 장비 알람 — 간헐적 하드웨어 고장
    s5 = make_base_log("S5")
    s5 = inject_alarm_repeat(s5, [200, 280, 360, 440, 520])
    scenarios.append(s5)

    # S6: CELL02~CELL03 SEC5에서 측정 신호 손실 — 기지국 정전
    s6 = make_base_log("S6")
    s6 = inject_measurement_loss(s6, sector_ids=[5], cell_from=2, cell_to=3)
    scenarios.append(s6)

    # S7: CELL02에서 트래픽 burst 후 회복 (대규모 이벤트)
    s7 = make_base_log("S7")
    s7 = inject_traffic_burst(s7, 200, 295, 6)
    scenarios.append(s7)

    # S8: 복합 장애 — 지연 drift + 패킷손실 + 알람 + 간섭
    s8 = make_base_log("S8")
    s8 = inject_latency_drift(s8, cell_from=2, slope=0.008)
    s8 = inject_packet_loss_drift(s8, cell_from=2, slope=0.012)
    s8 = inject_alarm_repeat(s8, [220, 260, 300, 340, 380])
    cell2_5_mask = _cell_mask(s8, cell_from=2, cell_to=5)
    s8.loc[cell2_5_mask, "interference_flag"] = 1
    scenarios.append(s8)

    # S9: 장애 감지 → 자동 복구 (파라미터 최적화)
    s9 = make_base_log("S9")
    s9 = inject_latency_spike(s9, 400, 510, 8)
    s9 = inject_alarm_repeat(s9, [420, 460])
    scenarios.append(s9)

    # S10: 복합 장애 후 복구 실패 — 현장 출동 필요
    s10 = make_base_log("S10")
    s10 = inject_latency_high_cells(s10, cell_from=2, cell_to=5, offset=8)
    s10 = inject_packet_loss_drift(s10, cell_from=2, slope=0.010)
    s10 = inject_alarm_repeat(s10, [250, 330, 410, 490])
    scenarios.append(s10)

    return pd.concat(scenarios, ignore_index=True)


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(project_root, "data/raw"), exist_ok=True)

    df = build_scenarios()
    save_path = os.path.join(project_root, "data/raw/network_kpi_logs.csv")
    df.to_csv(save_path, index=False)

    print("=" * 60)
    print("  5G 기지국 네트워크 KPI 시뮬레이션 로그 생성 완료")
    print("=" * 60)
    print(f"\n파일: {save_path}")
    print(f"총 row 수: {len(df)}")
    print(f"시나리오 수: {df['scenario_id'].nunique()}")
    print(f"\n컬럼 ({len(df.columns)}개):")
    for col in df.columns:
        print(f"  - {col}")
    print("\n측정 유형 분포:")
    print(df["measurement_type"].value_counts().to_string())
    print("\n셀 중요도 분포:")
    print(df["cell_priority"].value_counts().sort_index().to_string())
    print(f"\n측정 시간 범위: {df['measurement_time'].min()} ~ {df['measurement_time'].max()}")


if __name__ == "__main__":
    main()
