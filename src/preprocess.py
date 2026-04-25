import pandas as pd


def load_logs(path="data/raw/network_kpi_logs.csv"):
    """
    원본 기지국 KPI 로그 csv 로드
    """
    df = pd.read_csv(path)
    return df


def add_rolling_features(df):
    """
    이상 탐지에 쓸 rolling feature 추가
    scenario별로 따로 계산해야 함
    """
    result = []

    for scenario_id, group in df.groupby("scenario_id"):
        g = group.sort_values("timestamp").copy()

        # rolling mean / std
        g["latency_roll_mean"] = g["latency_ms"].rolling(window=20, min_periods=1).mean()
        g["latency_roll_std"] = g["latency_ms"].rolling(window=20, min_periods=1).std().fillna(0)

        g["jitter_roll_mean"] = g["jitter_ms"].rolling(window=20, min_periods=1).mean()
        g["packet_loss_roll_mean"] = g["packet_loss_pct"].rolling(window=20, min_periods=1).mean()

        # baseline 대비 차이
        g["latency_diff"] = g["latency_ms"] - g["latency_roll_mean"]
        g["packet_loss_diff"] = g["packet_loss_pct"] - g["packet_loss_roll_mean"]

        result.append(g)

    out = pd.concat(result, ignore_index=True)
    return out


def preprocess_logs(path="data/raw/network_kpi_logs.csv"):
    """
    전체 전처리 파이프라인
    """
    df = load_logs(path)
    df = add_rolling_features(df)
    return df
