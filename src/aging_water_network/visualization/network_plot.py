"""Plotly network map helpers for the Streamlit dashboard."""

from __future__ import annotations

from typing import Mapping

import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from aging_water_network.config import MIN_PRESSURE_HEAD_M


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
    fig.update_layout(template="plotly_white", height=560, margin={"l": 10, "r": 10, "t": 36, "b": 10})
    return fig


def _as_lookup(frame: pd.DataFrame | None, key: str, value: str) -> Mapping[str, float]:
    if frame is None or frame.empty or key not in frame or value not in frame:
        return {}
    return dict(zip(frame[key].astype(str), pd.to_numeric(frame[value], errors="coerce")))


def create_network_map(
    nodes: pd.DataFrame,
    pipes: pd.DataFrame,
    aging: pd.DataFrame | None = None,
    pressure: pd.DataFrame | None = None,
    valves: pd.DataFrame | None = None,
    pumps: pd.DataFrame | None = None,
    highlight_pipes: set[str] | list[str] | tuple[str, ...] | None = None,
    highlight_nodes: set[str] | list[str] | tuple[str, ...] | None = None,
    leak_pipe_id: str | None = None,
    leak_node_id: str | None = None,
    suspect_pipes: set[str] | list[str] | tuple[str, ...] | None = None,
    low_pressure_nodes: set[str] | list[str] | tuple[str, ...] | None = None,
    selectable: bool = False,
    title: str = "Network map",
) -> go.Figure:
    """Create a coordinate-based water-network map.

    Pipe color represents aging score. Node color represents pressure status when a
    pressure table is supplied.
    """

    required_node_cols = {"node_id", "x", "y"}
    required_pipe_cols = {"pipe_id", "from_node", "to_node"}
    if not required_node_cols.issubset(nodes.columns) or not required_pipe_cols.issubset(pipes.columns):
        return _empty_figure("Network map requires node_id/x/y and pipe_id/from_node/to_node columns.")

    node_positions = nodes.set_index(nodes["node_id"].astype(str))[["x", "y"]].to_dict("index")
    aging_lookup = _as_lookup(aging, "pipe_id", "aging_score")
    pressure_lookup = _as_lookup(pressure, "node_id", "pressure_head_m")
    pipe_highlights = {str(item) for item in (highlight_pipes or [])}
    node_highlights = {str(item) for item in (highlight_nodes or [])}
    suspect_pipe_ids = {str(item) for item in (suspect_pipes or [])}
    low_node_ids = {str(item) for item in (low_pressure_nodes or [])}
    leak_pipe = str(leak_pipe_id) if leak_pipe_id else ""
    leak_node = str(leak_node_id) if leak_node_id else ""

    fig = go.Figure()
    midpoint_rows = []
    annotations = []

    for _, pipe in pipes.iterrows():
        pipe_id = str(pipe["pipe_id"])
        from_node = str(pipe["from_node"])
        to_node = str(pipe["to_node"])
        start = node_positions.get(from_node)
        end = node_positions.get(to_node)
        if not start or not end:
            continue
        score = float(aging_lookup.get(pipe_id, 0.0))
        is_leak_pipe = pipe_id == leak_pipe
        is_suspect_pipe = pipe_id in suspect_pipe_ids
        is_highlight = pipe_id in pipe_highlights or is_leak_pipe or is_suspect_pipe
        if is_leak_pipe:
            color = "#dc2626"
            width = 11
            dash = "solid"
            trace_name = "Injected leak pipe"
        elif is_suspect_pipe:
            color = "#f59e0b"
            width = 8
            dash = "dash"
            trace_name = "Leak suspect pipe"
        elif is_highlight:
            color = "#e11d48"
            width = 9
            dash = "dash"
            trace_name = "Highlighted pipe"
        else:
            color = sample_colorscale("Turbo", [max(0.0, min(score, 1.0))])[0]
            width = 5
            dash = "solid"
            trace_name = "Aged pipe risk"
        fig.add_trace(
            go.Scatter(
                x=[start["x"], end["x"]],
                y=[start["y"], end["y"]],
                mode="lines",
                line={"width": width, "color": color, "dash": dash},
                hoverinfo="text",
                text=[
                    f"{pipe_id}<br>{from_node} -> {to_node}<br>Aging score: {score:.2f}",
                    f"{pipe_id}<br>{from_node} -> {to_node}<br>Aging score: {score:.2f}",
                ],
                customdata=[f"pipe:{pipe_id}", f"pipe:{pipe_id}"],
                name=trace_name,
                showlegend=False,
            )
        )
        midpoint_rows.append(
            {
                "pipe_id": pipe_id,
                "x": (start["x"] + end["x"]) / 2,
                "y": (start["y"] + end["y"]) / 2,
                "aging_score": score,
            }
        )
        annotations.append(
            {
                "x": (start["x"] + end["x"]) / 2,
                "y": (start["y"] + end["y"]) / 2,
                "xref": "x",
                "yref": "y",
                "text": pipe_id,
                "showarrow": False,
                "font": {"size": 10, "color": "#111827"},
                "bgcolor": "rgba(255,255,255,0.92)",
                "bordercolor": "rgba(17,24,39,0.55)",
                "borderwidth": 1,
                "borderpad": 2,
            }
        )

    node_pressure = [pressure_lookup.get(str(node_id)) for node_id in nodes["node_id"]]
    node_colors = []
    node_sizes = []
    node_symbols = []
    for value in node_pressure:
        node_id = str(nodes.iloc[len(node_colors)]["node_id"])
        if node_id == leak_node:
            node_colors.append("#e11d48")
            node_sizes.append(31)
            node_symbols.append("star")
        elif node_id in low_node_ids:
            node_colors.append("#b91c1c")
            node_sizes.append(28)
            node_symbols.append("circle-x")
        elif node_id in node_highlights:
            node_colors.append("#e11d48")
            node_sizes.append(27)
            node_symbols.append("circle")
        elif value is None or pd.isna(value):
            node_colors.append("#6b7280")
            node_sizes.append(24)
            node_symbols.append("circle")
        elif value < MIN_PRESSURE_HEAD_M:
            node_colors.append("#c0392b")
            node_sizes.append(26)
            node_symbols.append("circle-x")
        elif value < 20.0:
            node_colors.append("#d98c00")
            node_sizes.append(25)
            node_symbols.append("circle")
        else:
            node_colors.append("#1f7a4d")
            node_sizes.append(24)
            node_symbols.append("circle")

    node_text = []
    for _, node in nodes.iterrows():
        node_id = str(node["node_id"])
        pressure_text = "n/a"
        if node_id in pressure_lookup and pd.notna(pressure_lookup[node_id]):
            pressure_text = f"{float(pressure_lookup[node_id]):.1f} m"
        node_text.append(
            f"{node_id}<br>Type: {node.get('node_type', 'node')}<br>"
            f"Pressure head: {pressure_text}<br>Demand: {node.get('base_demand_lps', 'n/a')} L/s"
        )
        annotations.append(
            {
                "x": float(node["x"]),
                "y": float(node["y"]),
                "xref": "x",
                "yref": "y",
                "text": node_id,
                "showarrow": False,
                "font": {"size": 9, "color": "white"},
                "bgcolor": "rgba(17,24,39,0.72)",
                "bordercolor": "rgba(255,255,255,0.85)",
                "borderwidth": 1,
                "borderpad": 1,
            }
        )

    fig.add_trace(
        go.Scatter(
            x=nodes["x"],
            y=nodes["y"],
            mode="markers+text",
            text=nodes["node_id"],
            textposition="middle center",
            textfont={"size": 9, "color": "white"},
            marker={
                "size": node_sizes,
                "color": node_colors,
                "symbol": node_symbols,
                "line": {"width": 1.5, "color": "#111827"},
            },
            customdata=[f"node:{node_id}" for node_id in nodes["node_id"].astype(str)],
            hovertext=node_text,
            hoverinfo="text",
            name="nodes",
        )
    )

    if midpoint_rows:
        midpoint = pd.DataFrame(midpoint_rows)
        fig.add_trace(
            go.Scatter(
                x=midpoint["x"],
                y=midpoint["y"],
                mode="markers+text",
                text=midpoint["pipe_id"],
                textposition="middle center",
                textfont={"size": 9, "color": "#111827"},
                marker={
                    "size": 28 if selectable else 24,
                    "symbol": "square",
                    "color": "rgba(255, 255, 255, 0.86)",
                    "line": {"width": 1.2, "color": "rgba(17, 24, 39, 0.70)"},
                },
                customdata=[f"pipe:{pipe_id}" for pipe_id in midpoint["pipe_id"]],
                hovertext=[
                    f"Select {row.pipe_id}<br>Aging score: {row.aging_score:.2f}"
                    for row in midpoint.itertuples(index=False)
                ],
                hoverinfo="text",
                name="pipe id labels",
                showlegend=False,
            )
        )

    if valves is not None and not valves.empty and {"pipe_id", "valve_id"}.issubset(valves.columns):
        _add_asset_markers(fig, valves, pipes, node_positions, asset_id="valve_id", symbol="diamond", name="valves")
    if pumps is not None and not pumps.empty and {"pump_id", "from_node", "to_node"}.issubset(pumps.columns):
        pump_edges = pumps.rename(columns={"pump_id": "asset_id"})
        _add_direct_markers(fig, pump_edges, node_positions, asset_id="asset_id", symbol="square", name="pumps")

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=620,
        margin={"l": 10, "r": 10, "t": 42, "b": 10},
        xaxis={"visible": False, "scaleanchor": "y", "scaleratio": 1},
        yaxis={"visible": False},
        hovermode="closest",
        annotations=annotations,
    )
    _add_semantic_legend(fig)
    return fig


def _add_semantic_legend(fig: go.Figure) -> None:
    legend_items = [
        ("Aged pipe risk", "#22c55e", "solid"),
        ("Injected leak", "#dc2626", "solid"),
        ("Leak suspect", "#f59e0b", "dash"),
        ("Low pressure", "#b91c1c", "solid"),
    ]
    for name, color, dash in legend_items:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line={"color": color, "width": 6, "dash": dash},
                name=name,
                showlegend=True,
                hoverinfo="skip",
            )
        )


def _add_asset_markers(
    fig: go.Figure,
    assets: pd.DataFrame,
    pipes: pd.DataFrame,
    node_positions: Mapping[str, Mapping[str, float]],
    asset_id: str,
    symbol: str,
    name: str,
) -> None:
    pipe_lookup = pipes.set_index(pipes["pipe_id"].astype(str)).to_dict("index")
    rows = []
    for _, asset in assets.iterrows():
        pipe = pipe_lookup.get(str(asset["pipe_id"]))
        if not pipe:
            continue
        start = node_positions.get(str(pipe["from_node"]))
        end = node_positions.get(str(pipe["to_node"]))
        if start and end:
            rows.append(
                {
                    "x": (start["x"] + end["x"]) / 2,
                    "y": (start["y"] + end["y"]) / 2,
                    "label": str(asset[asset_id]),
                    "hover": "<br>".join(f"{key}: {value}" for key, value in asset.items()),
                }
            )
    if rows:
        data = pd.DataFrame(rows)
        fig.add_trace(
            go.Scatter(
                x=data["x"],
                y=data["y"],
                mode="markers+text",
                text=data["label"],
                textposition="bottom center",
                marker={"symbol": symbol, "size": 12, "color": "#111827"},
                hovertext=data["hover"],
                hoverinfo="text",
                name=name,
            )
        )


def _add_direct_markers(
    fig: go.Figure,
    assets: pd.DataFrame,
    node_positions: Mapping[str, Mapping[str, float]],
    asset_id: str,
    symbol: str,
    name: str,
) -> None:
    rows = []
    for _, asset in assets.iterrows():
        start = node_positions.get(str(asset["from_node"]))
        end = node_positions.get(str(asset["to_node"]))
        if start and end:
            rows.append(
                {
                    "x": (start["x"] + end["x"]) / 2,
                    "y": (start["y"] + end["y"]) / 2,
                    "label": str(asset[asset_id]),
                    "hover": "<br>".join(f"{key}: {value}" for key, value in asset.items()),
                }
            )
    if rows:
        data = pd.DataFrame(rows)
        fig.add_trace(
            go.Scatter(
                x=data["x"],
                y=data["y"],
                mode="markers+text",
                text=data["label"],
                textposition="bottom center",
                marker={"symbol": symbol, "size": 13, "color": "#2563eb"},
                hovertext=data["hover"],
                hoverinfo="text",
                name=name,
            )
        )
