"""Aging and risk Plotly helpers."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def create_aging_distribution(aging: pd.DataFrame, title: str = "Aging score distribution") -> go.Figure:
    if aging.empty or "aging_score" not in aging.columns:
        return _empty_figure("Aging score table is not available.")
    fig = px.histogram(
        aging,
        x="aging_score",
        nbins=20,
        range_x=[0, 1],
        color_discrete_sequence=["#4f6f52"],
        title=title,
    )
    fig.update_layout(template="plotly_white", height=390, xaxis_title="Aging score", yaxis_title="Pipe count")
    return fig


def create_top_risk_bar(
    aging: pd.DataFrame,
    top_n: int = 10,
    title: str = "Highest-risk aged pipes",
) -> go.Figure:
    if aging.empty or not {"pipe_id", "aging_score"}.issubset(aging.columns):
        return _empty_figure("Aging score table is not available.")
    frame = aging.sort_values("aging_score", ascending=False).head(top_n)
    fig = px.bar(
        frame,
        x="aging_score",
        y="pipe_id",
        orientation="h",
        color="aging_score",
        color_continuous_scale="Turbo",
        range_color=[0, 1],
        hover_data=[col for col in ["material", "install_year", "repair_count", "leak_history_count"] if col in frame.columns],
        title=title,
    )
    fig.update_layout(
        template="plotly_white",
        height=420,
        xaxis_title="Aging score",
        yaxis_title="Pipe",
        yaxis={"autorange": "reversed"},
    )
    return fig


def create_material_summary(aging: pd.DataFrame, title: str = "Material risk summary") -> go.Figure:
    if aging.empty or not {"material", "aging_score"}.issubset(aging.columns):
        return _empty_figure("Material risk summary requires material and aging_score columns.")
    frame = (
        aging.groupby("material", dropna=False)
        .agg(pipe_count=("pipe_id", "count"), mean_aging_score=("aging_score", "mean"))
        .reset_index()
        .sort_values("mean_aging_score", ascending=False)
    )
    fig = px.bar(
        frame,
        x="material",
        y="mean_aging_score",
        color="pipe_count",
        color_continuous_scale="Blues",
        hover_data=["pipe_count"],
        title=title,
    )
    fig.update_layout(template="plotly_white", height=390, xaxis_title="Material", yaxis_title="Mean aging score")
    return fig


def create_component_breakdown(
    aging: pd.DataFrame,
    pipe_id: str | None = None,
    title: str = "Aging component breakdown",
) -> go.Figure:
    component_cols = [
        col
        for col in aging.columns
        if col.endswith("_component") or col in {"age", "material_risk", "repair", "leak_history", "soil"}
    ]
    if aging.empty or not component_cols:
        return _empty_figure("Aging component columns are not available.")

    row = aging.sort_values("aging_score", ascending=False).iloc[0]
    if pipe_id is not None and "pipe_id" in aging.columns:
        match = aging[aging["pipe_id"].astype(str) == str(pipe_id)]
        if not match.empty:
            row = match.iloc[0]

    values = pd.DataFrame({"component": component_cols, "value": [row[col] for col in component_cols]})
    fig = px.bar(values, x="component", y="value", color="value", color_continuous_scale="Teal", title=title)
    fig.update_layout(template="plotly_white", height=390, xaxis_title="Component", yaxis_title="Component value")
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
    fig.update_layout(template="plotly_white", height=390, margin={"l": 10, "r": 10, "t": 36, "b": 10})
    return fig
