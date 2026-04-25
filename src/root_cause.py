import pandas as pd


def analyze_root_causes(df, judge_df):
    """
    scenario별 root cause 구조화
    출력 컬럼:
    - primary_cause
    - secondary_signal
    - confidence
    - evidence
    """
    rows = []

    for _, jrow in judge_df.iterrows():
        scenario_id = jrow["scenario_id"]

        reason_text = str(jrow["all_reasons"])

        has_measurement_loss = "measurement_loss" in reason_text
        has_alarm = "alarm_detected" in reason_text
        has_interference = "interference_event" in reason_text
        has_loss_jump = "packet_loss_jump" in reason_text
        has_loss_high = "packet_loss_high" in reason_text
        has_latency_high = "latency_high" in reason_text
        has_latency_spike = "latency_spike" in reason_text

        if has_measurement_loss:
            primary_cause = "Cell measurement probe failure (power outage or hardware failure)"
            secondary_signal = "jitter_ms unavailable"
            confidence = "High"
        elif has_latency_high and (has_loss_jump or has_loss_high):
            primary_cause = "Persistent network degradation with packet loss (backhaul/transport issue)"
            secondary_signal = "packet_loss_pct increase"
            confidence = "High"
        elif has_alarm and has_interference:
            primary_cause = "Combined fault with external interference-triggered instability"
            secondary_signal = "repeated alarm + interference_flag"
            confidence = "High"
        elif has_loss_jump or has_loss_high:
            primary_cause = "Packet loss degradation (transport equipment aging or link quality issue)"
            secondary_signal = "packet_loss_pct abnormal trend"
            confidence = "Medium"
        elif has_latency_high:
            primary_cause = "Persistent latency above SLA threshold (backhaul capacity shortage)"
            secondary_signal = "latency_ms above threshold"
            confidence = "Medium"
        elif has_latency_spike:
            primary_cause = "Transient latency spike (traffic burst or temporary congestion)"
            secondary_signal = "short latency_ms abnormal excursion"
            confidence = "Low"
        elif has_alarm:
            primary_cause = "Repeated equipment alarm pattern (intermittent hardware fault)"
            secondary_signal = "alarm_code recurrence"
            confidence = "Medium"
        else:
            primary_cause = "No significant abnormality"
            secondary_signal = "none"
            confidence = "Low"

        evidence_parts = []

        if has_latency_high:
            evidence_parts.append("latency_high_detected")
        if has_latency_spike:
            evidence_parts.append("latency_spike_detected")
        if has_loss_jump or has_loss_high:
            evidence_parts.append("packet_loss_abnormal")
        if has_alarm:
            evidence_parts.append("alarm_detected")
        if has_interference:
            evidence_parts.append("interference_event_detected")
        if has_measurement_loss:
            evidence_parts.append("measurement_loss_detected")

        evidence_parts.append(f"warning_ratio={jrow['warning_ratio']}")
        evidence_parts.append(f"critical_ratio={jrow['critical_ratio']}")
        evidence_parts.append(f"fail_ratio={jrow['fail_ratio']}")

        rows.append({
            "scenario_id": scenario_id,
            "primary_cause": primary_cause,
            "secondary_signal": secondary_signal,
            "confidence": confidence,
            "evidence": " | ".join(evidence_parts)
        })

    return pd.DataFrame(rows).sort_values("scenario_id").reset_index(drop=True)
