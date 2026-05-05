"""Leak-suspect ranking from residuals, topology proximity, and pipe aging."""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from aging_water_network.anomaly.residuals import pressure_residuals
from aging_water_network.control.evaluator import aged_pipe_scores


def rank_leak_suspects(
    tables: Mapping[str, pd.DataFrame],
    simulation: object,
    pressure_drop_threshold_m: float = -3.0,
) -> pd.DataFrame:
    """Rank pipes near unexpectedly low pressure sensors as leak-investigation suspects."""

    pipes = tables.get("pipes", pd.DataFrame())
    sensors = tables.get("sensors", pd.DataFrame())
    timeseries = tables.get("sensor_timeseries", pd.DataFrame())
    if pipes.empty or sensors.empty or timeseries.empty:
        return pd.DataFrame(columns=["pipe_id", "suspect_score", "reason"])

    residuals = pressure_residuals(sensors, timeseries, simulation)
    low = residuals[
        pd.to_numeric(residuals["residual"], errors="coerce") <= pressure_drop_threshold_m
    ]
    if low.empty:
        return pd.DataFrame(columns=["pipe_id", "suspect_score", "reason"])

    low_nodes = set(low["node_or_pipe_id"].astype(str))
    candidates = pipes[
        pipes["from_node"].astype(str).isin(low_nodes)
        | pipes["to_node"].astype(str).isin(low_nodes)
    ].copy()
    if candidates.empty:
        return pd.DataFrame(columns=["pipe_id", "suspect_score", "reason"])

    candidates["aging_score"] = aged_pipe_scores(candidates).to_numpy()
    candidates["near_low_pressure_sensor"] = True
    candidates["history_score"] = (
        pd.to_numeric(candidates.get("leak_history_count", 0), errors="coerce").fillna(0).clip(0, 3)
        / 3.0
    )
    candidates["suspect_score"] = (
        0.65 * candidates["aging_score"] + 0.35 * candidates["history_score"]
    ).round(3)
    candidates["reason"] = (
        "Adjacent to pressure sensor with observed pressure below simulated expectation."
    )
    return candidates.sort_values("suspect_score", ascending=False)[
        ["pipe_id", "from_node", "to_node", "aging_score", "suspect_score", "reason"]
    ].reset_index(drop=True)
