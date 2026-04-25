# NetPulse

> 5G Network KPI를 기반으로 이상을 탐지하고 상태를 판정하는 NOC 파이프라인. 3GPP 표준과 통계적 품질 관리(SPC)를 적용하여 네트워크 품질을 자동으로 모니터링함.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Tests](https://img.shields.io/badge/Tests-44%2F44%20PASS-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#license)

## 목차

- [프로젝트 개요](#프로젝트-개요)
- [주요 특징](#주요-특징)
- [기술 스택](#기술-스택)
- [빠른 시작](#빠른-시작)
- [아키텍처](#아키텍처)
- [프로젝트 구조](#프로젝트-구조)
- [테스트](#테스트)
- [배포](#배포)
- [라이선스](#라이선스)

---

## 프로젝트 개요

**NetPulse**는 5G 기지국(gNB)의 네트워크 KPI를 실시간으로 모니터링하는 통합 파이프라인임. 측정 데이터 → 이상 탐지 → 상태 판정 → 품질 분석 → NOC 에스컬레이션까지 11단계 처리 흐름을 구현하였으며, 3GPP TS 32.425/32.111 표준을 기반으로 설계됨.

### 핵심 목표

- **실시간 이상 탐지**: 9개의 규칙을 벡터화하여 초당 단위로 처리
- **상태 머신 관리**: GREEN → YELLOW → RED → RECOVERING → BLACKOUT 자동 상태 추적
- **통계적 품질 관리**: Cpk/Ppk + Western Electric 8 Rules로 공정 능력 평가
- **데이터 품질 검증**: 완전성/정합성/적시성/정확성 4차원 DQM 평가
- **자동 에스컬레이션**: 우선순위 산정에 따른 NOC 조치 자동화

---

## 주요 특징

### 🔍 9개 이상 탐지 규칙 (Rule-Based)

| 코드 | 규칙 | 임계값 | 판단 기준 |
|------|------|--------|----------|
| R1 | `latency_high` | ≥ 18ms | 5G eMBB SLA 기준 |
| R2 | `latency_spike` | \|Δ\| ≥ 5ms | 순간 변동 감지 |
| R3 | `packet_loss_high` | ≥ 3.0% | 전송 품질 이상 |
| R4 | `packet_loss_jump` | Δ ≥ 1.0% | 손실률 급증 |
| R5 | `alarm_detected` | code ≠ 0 | 장비 하드웨어 알람 |
| R6 | `measurement_loss` | jitter ≤ 0.1ms | 측정 신호 손실 |
| R7 | `interference_event` | flag = 1 | 외부 간섭 감지 |
| R8 | `peak_hour_congestion` | 18~22h + latency ≥ 15ms | 피크시간 혼잡 |
| R9 | `priority_cell_degradation` | 중요도≥4 + 데이터 | 핵심 셀 성능 저하 |

### 🔄 5-State 머신

```
GREEN ──→ YELLOW ──→ RED ──→ RECOVERING ──→ GREEN
                      ↓
                  BLACKOUT (긴급 차단)
```

### 📊 품질 관리 (SPC/QoS)

- **Cpk/Ppk**: 공정 능력 지수 (1.33 이상 = 우수)
- **Western Electric 8 Rules**: 통계적 OOC(Out-of-Control) 판정
- **SLA 범위 설정**: Latency (3~20ms), Jitter (0.5~8ms), Packet Loss (0~3%)

### 📈 데이터 품질 관리 (DQM)

4차원 평가로 측정 데이터의 신뢰도를 산정:

- **완전성** (30%): NULL/누락 비율 ≤ 1%
- **정합성** (25%): 값 범위/타입 일치 ≤ 0.5%
- **적시성** (20%): 측정 지연 ≤ 50ms
- **정확성** (25%): 로직 일관성 ≥ 99%

최종 DQM Score ≥ 95점 = PASS

### 📦 정기 점검 배치

- **일일 KPI 집계**: 셀별/측정유형별 통계
- **SLA 위반 자동 식별**: 임계값 초과 건수 집계
- **에스컬레이션 우선순위 산정**: URGENT / HIGH / MEDIUM / LOW
- **정합성 검증**: 원본 측정 ↔ 집계 데이터 교차 검증

---

## 기술 스택

| 범주 | 기술 |
|------|------|
| **Language** | Python 3.10 |
| **Data Processing** | pandas, numpy (벡터화 연산) |
| **Database** | PostgreSQL 16 (8 tables + 9 views) |
| **Visualization** | Streamlit, Plotly (6-tab dashboard) |
| **Infrastructure** | Docker, docker-compose |
| **CI/CD** | GitHub Actions (lint → test → build) |
| **Testing** | pytest (44 integration + unit tests) |
| **Linting** | ruff |

---

## 빠른 시작

### Prerequisites

- Python 3.10+
- PostgreSQL 16 (또는 Docker)
- Docker & docker-compose (옵션)

### Installation

```bash
# 1. Clone repository
git clone https://github.com/jeong-inn/NetPulse.git
cd NetPulse

# 2. Virtual environment 설정
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 또는
venv\Scripts\activate  # Windows

# 3. 의존성 설치
pip install -r requirements.txt
```

### Running the Pipeline

**로컬 실행 (SQLite 모드)**:

```bash
# 테스트 데이터 생성
python3 src/generate_logs.py

# 파이프라인 실행
python3 src/main.py

# 테스트 실행
python3 -m pytest tests/ -v --tb=short
```

**대시보드 실행**:

```bash
streamlit run app.py
# http://localhost:8501에서 확인
```

**Docker로 실행 (PostgreSQL 포함)**:

```bash
docker-compose up --build
# 대시보드: http://localhost:8501
# PostgreSQL: localhost:5432
```

---

## 아키텍처

### 11-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│ [1] 데이터 로드 & 전처리                                     │
│     ↓                                                         │
│ [2] 이상 탐지 (9개 규칙, numpy 벡터화)                       │
│     ↓                                                         │
│ [3] 상태 머신 (GREEN/YELLOW/RED/RECOVERING/BLACKOUT)        │
│     ↓                                                         │
│ [4] 시나리오 판정 (PASS/PASS_WITH_WARNING/FAIL)            │
│     ↓                                                         │
│ [5] 결과 검증 (Expected vs Actual)                          │
│     ↓                                                         │
│ [6] SPC/QoS 분석 (Cpk/Ppk + WE Rules)                       │
│     ↓                                                         │
│ [7] 원인 분석 (3GPP 도메인 매핑)                            │
│     ↓                                                         │
│ [8] DQM 품질 검증 (4차원 점수)                              │
│     ↓                                                         │
│ [9] 정기 점검 배치 (KPI/SLA/에스컬레이션/정합성)           │
│     ↓                                                         │
│ [10] NOC 리포트 (JSON + LLM)                                 │
│     ↓                                                         │
│ [11] PostgreSQL 저장 (8 tables + 9 views)                    │
└─────────────────────────────────────────────────────────────┘
```

### 주요 모듈

| 파일 | 역할 | 행 |
|------|------|-----|
| `generate_logs.py` | 10K 합성 KPI 로그 생성 (10 scenarios) | 250 |
| `anomaly_detector.py` | 9개 규칙 벡터화 탐지 | 180 |
| `state_engine.py` | 5-state 머신 관리 | 120 |
| `judge.py` | 최종 판정 로직 | 110 |
| `validator.py` | Expected vs Actual 검증 | 90 |
| `policy_engine.py` | 액션 우선순위 & Release Gate | 120 |
| `spc.py` | Cpk/Ppk + WE Rules | 250 |
| `root_cause.py` | 원인 분석 (도메인 기반) | 140 |
| `batch_processor.py` | 정기 점검 배치 | 305 |
| `dq_monitor.py` | DQM 4차원 검증 | 180 |
| `operator_report.py` | NOC 리포트 템플릿 | 80 |
| `llm_reporter.py` | LLM 자연언어 리포트 | 140 |
| `db_writer.py` | PostgreSQL 저장 | 200 |
| `main.py` | 11단계 오케스트레이션 | 280 |

**총 코드량**: ~2,400 LOC (테스트 제외)

---

## 프로젝트 구조

```
NetPulse/
├── src/                              # 핵심 파이프라인
│   ├── generate_logs.py              # 합성 데이터 생성
│   ├── preprocess.py                 # 피쳐 엔지니어링
│   ├── anomaly_detector.py           # 9개 규칙
│   ├── state_engine.py               # 상태 관리
│   ├── judge.py                      # 최종 판정
│   ├── validator.py                  # 검증 로직
│   ├── policy_engine.py              # 액션 정책
│   ├── spc.py                        # SPC/QoS
│   ├── root_cause.py                 # 원인 분석
│   ├── batch_processor.py            # 정기 배치
│   ├── dq_monitor.py                 # 품질 검증
│   ├── operator_report.py            # 리포트 템플릿
│   ├── llm_reporter.py               # LLM 통합
│   ├── db_writer.py                  # DB 저장
│   └── main.py                       # 오케스트레이션
├── tests/
│   ├── test_pipeline.py              # 27 통합 테스트
│   └── test_spc.py                   # 17 단위 테스트
├── data/
│   ├── raw/                          # 원본 합성 로그
│   ├── processed/                    # 처리된 데이터
│   └── scenarios/scenario_specs.json # 10 시나리오 정의
├── db/
│   └── init.sql                      # 스키마 + 뷰
├── app.py                            # Streamlit 대시보드
├── Dockerfile                        # 컨테이너 이미지
├── docker-compose.yml                # 서비스 구성
├── requirements.txt                  # Python 의존성
├── .github/workflows/ci.yml          # CI 파이프라인
└── README.md                         # 이 문서
```

---

## 10개 시나리오

파이프라인을 검증하기 위해 10가지 실무 시나리오를 시뮬레이션:

| ID | 설명 | 예상 판정 | 대응 액션 |
|----|------|----------|-----------|
| S1 | 정상 운영 (baseline) | PASS | NO_ACTION |
| S2 | 지연 스파이크 후 자가 회복 | PASS_WITH_WARNING | ENHANCED_MONITORING |
| S3 | 지연시간 지속 상승 (백홀 부족) | FAIL | NOC_ESCALATION |
| S4 | 패킷 손실률 점진 증가 (노후화) | FAIL | FIELD_INSPECTION |
| S5 | 반복 장비 알람 (간헐적 고장) | FAIL | NOC_ESCALATION |
| S6 | 측정 신호 손실 (기지국 정전) | FAIL | CELL_SHUTDOWN |
| S7 | 트래픽 burst 후 회복 (대규모 이벤트) | PASS_WITH_WARNING | ENHANCED_MONITORING |
| S8 | 복합 장애 (지연+손실+알람+간섭) | FAIL | EMERGENCY_HALT |
| S9 | 장애 감지 후 자동 복구 | PASS_WITH_WARNING | PARAMETER_OPTIMIZATION |
| S10 | 복구 실패 (현장 출동 필요) | FAIL | EMERGENCY_HALT |

---

## 테스트

### 단위 테스트 & 통합 테스트

```bash
python3 -m pytest tests/ -v --tb=short
```

**결과**: **44/44 PASS** (1.65s)

- **Pipeline Integration Tests** (27개)
  - 데이터 생성, 이상 탐지, 상태 머신, 배치 처리, DQM, 시나리오 판정
  
- **SPC Unit Tests** (17개)
  - Cpk/Ppk 계산, Western Electric 8 Rules, 안정성 검증

### 커버리지 확인

```bash
python3 -m pytest tests/ --cov=src --cov-report=html
```

---

## 배포

### 로컬 개발

```bash
python3 src/main.py
streamlit run app.py
```

### Docker로 배포

```bash
docker-compose up -d
# 또는 특정 서비스만
docker-compose up pipeline-service
docker-compose up dashboard
```

### GitHub Actions CI/CD

`.github/workflows/ci.yml`에 정의된 자동화 파이프라인:

1. **Lint** (ruff): 코드 품질 검사
2. **Test** (pytest + PostgreSQL): 통합 테스트
3. **Build**: Docker 이미지 생성

---

## 주요 성능 지표

| 항목 | 결과 |
|------|------|
| **처리 속도** | 10,000행 = 0.9초 |
| **이상 탐지** | numpy 벡터화 (~50x vs iterrows) |
| **테스트 커버리지** | 44/44 PASS (100%) |
| **데이터베이스** | 8 tables + 9 views |
| **파이프라인 단계** | 11 stages (end-to-end) |

---

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됨. [LICENSE](LICENSE) 파일 참조.

---

## 저자

**정인** — 2026년 LG U+ 공채 지원 포트폴리오

- GitHub: [@jeong-inn](https://github.com/jeong-inn)
- Email: sfutureain@gmail.com

---

**NetPulse**로 5G 네트워크 운영의 자동화와 지능화를 실현하는 것을 목표로 함.
