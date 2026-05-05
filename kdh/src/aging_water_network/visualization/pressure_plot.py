"""Pressure and head-loss Plotly helpers."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from aging_water_network.config import (
    HEAD_LOSS_GRADIENT_CRITICAL,
    HEAD_LOSS_GRADIENT_WARNING,
    MARGINAL_PRESSURE_HEAD_M,
    MIN_PRESSURE_HEAD_M,
)


def classify_pressure_status(pressure_head_m: float) -> str:
    if pressure_head_m < MIN_PRESSURE_HEAD_M:
        return "low"
    if pressure_head_m < MARGINAL_PRESSURE_HEAD_M:
        return "marginal"
    return "ok"


def create_pressure_bar(pressure: pd.DataFrame, title: str = "Node pressure head") -> go.Figure:
    if pressure.empty or not {"node_id", "pressure_head_m"}.issubset(pressure.columns):
        return _empty_figure("Pressure table is not available.")

    frame = pressure.copy()
    frame["status"] = frame["pressure_head_m"].apply(classify_pressure_status)
    frame = frame.sort_values("pressure_head_m")
    fig = px.bar(
        frame,
        x="node_id",
        y="pressure_head_m",
        color="status",
        color_discrete_map={"low": "#c0392b", "marginal": "#d98c00", "ok": "#1f7a4d"},
        hover_data=[col for col in ["elevation_m", "hydraulic_grade_m"] if col in frame.columns],
        title=title,
    )
    fig.add_hline(
        y=MIN_PRESSURE_HEAD_M,
        line_dash="dash",
        line_color="#c0392b",
        annotation_text="15 m minimum",
    )
    fig.add_hline(
        y=MARGINAL_PRESSURE_HEAD_M,
        line_dash="dot",
        line_color="#d98c00",
        annotation_text="20 m marginal",
    )
    fig.update_layout(template="plotly_white", height=430, xaxis_title="Node", yaxis_title="Pressure head (m)")
    return fig


def create_pressure_timeseries(
    sensors: pd.DataFrame,
    sensor_timeseries: pd.DataFrame,
    title: str = "Observed pressure sensor series",
) -> go.Figure:
    needed_sensors = {"sensor_id", "sensor_type", "node_or_pipe_id"}
    if sensors.empty or sensor_timeseries.empty or not needed_sensors.issubset(sensors.columns):
        return _empty_figure("Pressure sensor time series is not available.")
    if not {"timestamp", "sensor_id", "value"}.issubset(sensor_timeseries.columns):
        return _empty_figure("Pressure sensor time series is missing timestamp/sensor_id/value columns.")

    pressure_sensors = sensors[sensors["sensor_type"].astype(str).str.lower() == "pressure"]
    if pressure_sensors.empty:
        return _empty_figure("No pressure sensors were found.")

    frame = sensor_timeseries.merge(
        pressure_sensors[["sensor_id", "node_or_pipe_id"]],
        on="sensor_id",
        how="inner",
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    fig = px.line(
        frame,
        x="timestamp",
        y="value",
        color="node_or_pipe_id",
        markers=True,
        title=title,
        labels={"value": "Pressure head (m)", "node_or_pipe_id": "Node"},
    )
    fig.add_hline(y=MIN_PRESSURE_HEAD_M, line_dash="dash", line_color="#c0392b")
    fig.update_layout(template="plotly_white", height=430)
    return fig


def create_headloss_bar(headloss: pd.DataFrame, title: str = "Pipe head-loss gradient") -> go.Figure:
    if headloss.empty or not {"pipe_id", "head_loss_gradient"}.issubset(headloss.columns):
        return _empty_figure("Head-loss table is not available.")
    frame = headloss.copy()
    frame["severity"] = "normal"
    frame.loc[frame["head_loss_gradient"] >= HEAD_LOSS_GRADIENT_WARNING, "severity"] = "warning"
    frame.loc[frame["head_loss_gradient"] >= HEAD_LOSS_GRADIENT_CRITICAL, "severity"] = "critical"
    frame = frame.sort_values("head_loss_gradient", ascending=False)
    fig = px.bar(
        frame,
        x="pipe_id",
        y="head_loss_gradient",
        color="severity",
        color_discrete_map={"normal": "#1f7a4d", "warning": "#d98c00", "critical": "#c0392b"},
        hover_data=[col for col in ["head_loss_m", "flow_lps", "possible_cause"] if col in frame.columns],
        title=title,
    )
    fig.add_hline(y=HEAD_LOSS_GRADIENT_WARNING, line_dash="dot", line_color="#d98c00")
    fig.add_hline(y=HEAD_LOSS_GRADIENT_CRITICAL, line_dash="dash", line_color="#c0392b")
    fig.update_layout(
        template="plotly_white",
        height=430,
        xaxis_title="Pipe",
        yaxis_title="Head-loss gradient (m/m)",
    )
    return fig


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"size": 15},
    )
    fig.update_layout(template="plotly_white", height=430, margin={"l": 10, "r": 10, "t": 36, "b": 10})
    return fig
