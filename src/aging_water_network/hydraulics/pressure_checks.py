"""Pressure-head constraint checks for simulator outputs."""

from __future__ import annotations

import pandas as pd


def classify_pressure_severity(pressure_head_m: float, threshold_m: float = 15.0) -> str:
    margin = pressure_head_m - threshold_m
    if margin < -5.0:
        return "critical"
    if margin < 0.0:
        return "violation"
    if margin < 2.0:
        return "warning"
    return "ok"


def detect_pressure_violations(
    node_results: pd.DataFrame,
    threshold_m: float = 15.0,
    include_warnings: bool = False,
) -> pd.DataFrame:
    """Return pressure-head rows below the minimum service constraint."""

    if node_results.empty:
        return pd.DataFrame(columns=["node_id", "pressure_head_m", "threshold_m", "pressure_margin_m", "severity"])

    result = node_results.copy()
    result["threshold_m"] = float(threshold_m)
    result["pressure_margin_m"] = result["pressure_head_m"] - result["threshold_m"]
    result["severity"] = result["pressure_head_m"].map(lambda value: classify_pressure_severity(float(value), threshold_m))
    severities = {"critical", "violation", "warning"} if include_warnings else {"critical", "violation"}
    return (
        result[result["severity"].isin(severities)][["node_id", "pressure_head_m", "threshold_m", "pressure_margin_m", "severity"]]
        .sort_values(["pressure_margin_m", "node_id"])
        .reset_index(drop=True)
    )


def detect_aged_pipe_pressure_stress(
    pipe_results: pd.DataFrame,
    node_results: pd.DataFrame,
    aging_threshold: float = 0.7,
    pressure_threshold_m: float = 45.0,
) -> pd.DataFrame:
    """Flag aged pipes whose endpoint pressure is high enough to raise burst stress."""

    if pipe_results.empty or node_results.empty:
        return pd.DataFrame(
            columns=["pipe_id", "mean_endpoint_pressure_head_m", "aging_score", "stress_margin_m", "severity"]
        )

    pressure = node_results[["node_id", "pressure_head_m"]]
    result = pipe_results.merge(pressure, left_on="from_node", right_on="node_id", how="left").rename(
        columns={"pressure_head_m": "from_pressure_head_m"}
    )
    result = result.merge(pressure, left_on="to_node", right_on="node_id", how="left").rename(
        columns={"pressure_head_m": "to_pressure_head_m"}
    )
    result["mean_endpoint_pressure_head_m"] = result[["from_pressure_head_m", "to_pressure_head_m"]].mean(axis=1)
    result["stress_margin_m"] = result["mean_endpoint_pressure_head_m"] - pressure_threshold_m
    flags = result[(result.get("aging_score", 0.0) >= aging_threshold) & (result["stress_margin_m"] > 0.0)].copy()
    if flags.empty:
        return pd.DataFrame(
            columns=["pipe_id", "mean_endpoint_pressure_head_m", "aging_score", "stress_margin_m", "severity"]
        )
    flags["severity"] = flags["stress_margin_m"].map(lambda value: "critical" if value > 10.0 else "warning")
    return flags[
        ["pipe_id", "mean_endpoint_pressure_head_m", "aging_score", "stress_margin_m", "severity"]
    ].sort_values(["stress_margin_m", "pipe_id"], ascending=[False, True]).reset_index(drop=True)
