"""Residual calculations between sensor observations and simulated hydraulics."""

from __future__ import annotations

from typing import Any

import pandas as pd

from aging_water_network.control.evaluator import extract_node_pressures, extract_pipe_metrics


def latest_sensor_values(
    sensors: pd.DataFrame,
    sensor_timeseries: pd.DataFrame,
    sensor_type: str | None = None,
) -> pd.DataFrame:
    if sensors.empty or sensor_timeseries.empty:
        return pd.DataFrame(
            columns=["sensor_id", "node_or_pipe_id", "sensor_type", "observed_value"]
        )
    joined = sensor_timeseries.merge(sensors, on="sensor_id", how="left")
    if sensor_type is not None:
        joined = joined[joined["sensor_type"].astype(str).str.lower().eq(sensor_type.lower())]
    if joined.empty:
        return pd.DataFrame(
            columns=["sensor_id", "node_or_pipe_id", "sensor_type", "observed_value"]
        )
    joined["timestamp"] = pd.to_datetime(joined["timestamp"], errors="coerce")
    latest = joined.sort_values("timestamp").groupby("sensor_id", as_index=False).tail(1)
    return latest.rename(columns={"value": "observed_value"})[
        ["sensor_id", "node_or_pipe_id", "sensor_type", "observed_value"]
    ]


def pressure_residuals(
    sensors: pd.DataFrame, sensor_timeseries: pd.DataFrame, simulation: Any
) -> pd.DataFrame:
    observed = latest_sensor_values(sensors, sensor_timeseries, sensor_type="pressure")
    pressures = extract_node_pressures(simulation).rename(
        columns={"node_id": "node_or_pipe_id", "pressure_head_m": "simulated_value"}
    )
    residuals = observed.merge(pressures, on="node_or_pipe_id", how="left")
    residuals["residual"] = pd.to_numeric(
        residuals["observed_value"], errors="coerce"
    ) - pd.to_numeric(residuals["simulated_value"], errors="coerce")
    return residuals


def flow_residuals(
    sensors: pd.DataFrame, sensor_timeseries: pd.DataFrame, simulation: Any
) -> pd.DataFrame:
    observed = latest_sensor_values(sensors, sensor_timeseries, sensor_type="flow")
    pipe_metrics = extract_pipe_metrics(simulation)
    if "flow_lps" in pipe_metrics.columns:
        simulated = pipe_metrics[["pipe_id", "flow_lps"]].rename(
            columns={"pipe_id": "node_or_pipe_id", "flow_lps": "simulated_value"}
        )
    else:
        simulated = pd.DataFrame(columns=["node_or_pipe_id", "simulated_value"])
    residuals = observed.merge(simulated, on="node_or_pipe_id", how="left")
    residuals["residual"] = pd.to_numeric(
        residuals["observed_value"], errors="coerce"
    ) - pd.to_numeric(residuals["simulated_value"], errors="coerce")
    return residuals


def residual_summary(
    sensors: pd.DataFrame, sensor_timeseries: pd.DataFrame, simulation: Any
) -> dict[str, pd.DataFrame]:
    return {
        "pressure": pressure_residuals(sensors, sensor_timeseries, simulation),
        "flow": flow_residuals(sensors, sensor_timeseries, simulation),
    }
