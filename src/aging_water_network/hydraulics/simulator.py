"""Hydraulic simulation entry points with a deterministic local fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import networkx as nx
import numpy as np
import pandas as pd

from aging_water_network.aging.roughness import compute_hydraulic_params
from aging_water_network.aging.scoring import compute_all_aging_scores
from aging_water_network.data.loaders import ensure_mock_data
from aging_water_network.data.validators import validate_mock_data
from aging_water_network.hydraulics.headloss import hazen_williams_headloss_m
from aging_water_network.hydraulics.pressure_checks import detect_aged_pipe_pressure_stress, detect_pressure_violations
from aging_water_network.topology.criticality import compute_pipe_criticality

MATERIAL_BASE_C = {
    "PVC": 150.0,
    "HDPE": 145.0,
    "ductile_iron": 130.0,
    "concrete": 120.0,
    "steel": 115.0,
    "cast_iron": 100.0,
}
FALLBACK_HEADLOSS_CALIBRATION = 16.0


def _normalize(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    max_value = float(values.max()) if len(values) else 0.0
    return values * 0.0 if max_value <= 0 else values / max_value


def compute_fallback_aging_scores(pipes: pd.DataFrame, current_year: int = 2026) -> pd.DataFrame:
    """Compatibility wrapper around the package aging model."""

    aging = compute_all_aging_scores(pipes, current_year=current_year)
    if "aging_score_override" not in pipes.columns:
        return aging
    override = pipes[["pipe_id", "aging_score_override"]].copy()
    override["aging_score_override"] = pd.to_numeric(
        override["aging_score_override"], errors="coerce"
    )
    aging = aging.merge(override, on="pipe_id", how="left")
    mask = aging["aging_score_override"].notna()
    aging.loc[mask, "aging_score"] = aging.loc[mask, "aging_score_override"].clip(0.0, 1.0)
    return aging.drop(columns=["aging_score_override"])


def compute_pipe_hydraulic_params(pipes: pd.DataFrame, aging_scores: pd.DataFrame) -> pd.DataFrame:
    """Compatibility wrapper around the package hydraulic mapping model."""

    params = compute_hydraulic_params(pipes, aging_scores)
    return params.merge(aging_scores[["pipe_id", "aging_score"]], on="pipe_id", how="left")


def _source_heads(tables: Mapping[str, pd.DataFrame], source_head_delta_m: float = 0.0) -> dict[str, float]:
    reservoirs = tables.get("reservoirs", pd.DataFrame())
    if reservoirs.empty:
        roots = tables["nodes"].loc[tables["nodes"]["node_type"].eq("reservoir"), "node_id"].astype(str).tolist()
        return {roots[0] if roots else str(tables["nodes"]["node_id"].iloc[0]): 70.0 + source_head_delta_m}
    return {str(row["node_id"]): float(row["head_m"]) + source_head_delta_m for row in reservoirs.to_dict("records")}


def _pump_gain_by_edge(tables: Mapping[str, pd.DataFrame]) -> dict[tuple[str, str], float]:
    gains: dict[tuple[str, str], float] = {}
    for row in tables.get("pumps", pd.DataFrame()).to_dict("records"):
        if str(row.get("status", "on")).lower() == "off":
            continue
        gain = float(row.get("base_head_gain_m", 0.0)) * float(row.get("speed_multiplier", 1.0))
        gains[(str(row["from_node"]), str(row["to_node"]))] = gain
    return gains


def _valve_status_by_pipe(valves: pd.DataFrame) -> dict[str, str]:
    statuses: dict[str, str] = {}
    if valves.empty:
        return statuses
    rank = {"open": 0, "partially_open": 1, "closed": 2}
    for row in valves.to_dict("records"):
        pipe_id = str(row["pipe_id"])
        status = str(row.get("status", "open")).lower()
        if rank.get(status, 0) >= rank.get(statuses.get(pipe_id, "open"), 0):
            statuses[pipe_id] = status
    return statuses


def _build_hydraulic_graph(
    pipes: pd.DataFrame,
    params: pd.DataFrame,
    valve_status_by_pipe: Mapping[str, str] | None = None,
) -> nx.Graph:
    param_lookup = params.set_index("pipe_id").to_dict("index")
    status_lookup = dict(valve_status_by_pipe or {})
    graph = nx.Graph()
    for row in pipes.to_dict("records"):
        pipe_id = str(row["pipe_id"])
        param = param_lookup[pipe_id]
        status = status_lookup.get(pipe_id, "open")
        status_multiplier = {"open": 1.0, "partially_open": 30.0, "closed": 1_000_000.0}.get(status, 1.0)
        resistance = float(row["length_m"]) / (
            max(float(param["adjusted_roughness_c"]), 1.0) ** 1.852 * max(float(row["diameter_mm"]) / 1000.0, 1e-6) ** 4.871
        ) * status_multiplier
        graph.add_edge(str(row["from_node"]), str(row["to_node"]), weight=resistance, valve_status=status, **row)
    return graph


def _tree_edge_demands(
    graph: nx.Graph,
    root: str,
    nodes: pd.DataFrame,
) -> tuple[dict[str, str], dict[tuple[str, str], float]]:
    predecessors = nx.dijkstra_predecessor_and_distance(graph, root, weight="weight")[0]
    parent = {node: preds[0] for node, preds in predecessors.items() if preds}
    children: dict[str, list[str]] = {node: [] for node in graph.nodes}
    for node, parent_id in parent.items():
        children[parent_id].append(node)

    demand = nodes.set_index("node_id")["base_demand_lps"].astype(float).to_dict()
    subtree_demand: dict[str, float] = {}

    def visit(node_id: str) -> float:
        total = float(demand.get(node_id, 0.0))
        for child in children.get(node_id, []):
            total += visit(child)
        subtree_demand[node_id] = total
        return total

    visit(root)
    edge_demands = {(parent_id, node): subtree_demand.get(node, 0.0) for node, parent_id in parent.items()}
    return parent, edge_demands


def run_fallback_simulation(
    tables: Mapping[str, pd.DataFrame],
    min_pressure_head_m: float = 15.0,
    demand_multiplier: float = 1.0,
    source_head_delta_m: float = 0.0,
    valve_status_overrides: Mapping[str, str] | None = None,
    include_minor_losses: bool = True,
) -> dict[str, pd.DataFrame | dict[str, object]]:
    """Run a deterministic pressure/flow approximation without WNTR."""

    copied_tables = {name: frame.copy() for name, frame in tables.items()}
    copied_tables["nodes"]["base_demand_lps"] = copied_tables["nodes"]["base_demand_lps"].astype(float) * float(demand_multiplier)
    validate_mock_data(copied_tables)

    pipes = copied_tables["pipes"].copy()
    valves = copied_tables.get("valves", pd.DataFrame()).copy()
    if valve_status_overrides and not valves.empty:
        for valve_id, status in valve_status_overrides.items():
            valves.loc[valves["valve_id"].astype(str) == str(valve_id), "status"] = status
        copied_tables["valves"] = valves

    pipe_criticality = compute_pipe_criticality(copied_tables)
    if not pipe_criticality.empty:
        topo = pipe_criticality[["pipe_id", "edge_betweenness_centrality"]].copy()
        max_edge = float(topo["edge_betweenness_centrality"].max() or 0.0)
        topo["topology_component"] = (
            topo["edge_betweenness_centrality"] / max_edge if max_edge > 0 else 0.0
        )
        pipes = pipes.merge(topo[["pipe_id", "topology_component"]], on="pipe_id", how="left")
        pipes["topology_component"] = pipes["topology_component"].fillna(0.0)

    effective_valves = valves.copy()
    if not effective_valves.empty:
        status = effective_valves["status"].astype(str).str.lower()
        effective_valves.loc[status.eq("partially_open"), "minor_loss_k"] = (
            effective_valves.loc[status.eq("partially_open"), "minor_loss_k"].astype(float) + 3.0
        )
        effective_valves.loc[status.eq("closed"), "minor_loss_k"] = (
            effective_valves.loc[status.eq("closed"), "minor_loss_k"].astype(float) + 30.0
        )
        if not include_minor_losses:
            effective_valves["minor_loss_k"] = 0.0

    aging_scores = compute_fallback_aging_scores(pipes)
    pipe_params = compute_hydraulic_params(pipes, aging_scores, valves_df=effective_valves)
    if not include_minor_losses:
        pipe_params["minor_loss_k"] = 0.0
    pipe_params = pipe_params.merge(aging_scores[["pipe_id", "aging_score"]], on="pipe_id", how="left")
    status_by_pipe = _valve_status_by_pipe(effective_valves)

    graph = _build_hydraulic_graph(pipes, pipe_params, status_by_pipe)
    source_heads = _source_heads(copied_tables, source_head_delta_m=source_head_delta_m)
    root = max(source_heads, key=lambda node_id: source_heads[node_id])
    parent, edge_demands = _tree_edge_demands(graph, root, copied_tables["nodes"])
    pump_gain = _pump_gain_by_edge(copied_tables)
    param_lookup = pipe_params.set_index("pipe_id").to_dict("index")

    hgl = {root: source_heads[root]}
    distances = nx.single_source_dijkstra_path_length(graph, root, weight="weight")
    path_order = sorted(distances, key=distances.get)
    for node_id in path_order:
        if node_id == root or node_id not in parent:
            continue
        parent_id = parent[node_id]
        edge = graph[parent_id][node_id]
        flow = edge_demands.get((parent_id, node_id), 0.0)
        param = param_lookup[edge["pipe_id"]]
        loss = FALLBACK_HEADLOSS_CALIBRATION * abs(
            hazen_williams_headloss_m(
                flow,
                edge["length_m"],
                edge["diameter_mm"],
                param["adjusted_roughness_c"],
                param["minor_loss_k"],
            )
        )
        hgl[node_id] = hgl[parent_id] + pump_gain.get((parent_id, node_id), 0.0) - loss

    node_results = copied_tables["nodes"].copy()
    node_results["hydraulic_grade_m"] = node_results["node_id"].map(hgl).fillna(source_heads[root])
    node_results["pressure_head_m"] = node_results["hydraulic_grade_m"] - node_results["elevation_m"].astype(float)
    node_results["pressure_head_m"] = node_results["pressure_head_m"].round(6)
    node_results["hydraulic_grade_m"] = node_results["hydraulic_grade_m"].round(6)
    node_results["is_pressure_compliant"] = node_results["pressure_head_m"] >= float(min_pressure_head_m)
    node_results["pressure_status"] = node_results["pressure_head_m"].map(_pressure_status)

    pipe_rows = []
    for row in pipes.to_dict("records"):
        from_node = str(row["from_node"])
        to_node = str(row["to_node"])
        pipe_id = str(row["pipe_id"])
        if parent.get(to_node) == from_node:
            flow = edge_demands.get((from_node, to_node), 0.0)
        elif parent.get(from_node) == to_node:
            flow = -edge_demands.get((to_node, from_node), 0.0)
        else:
            head_delta = float(hgl.get(from_node, source_heads[root]) - hgl.get(to_node, source_heads[root]))
            flow = np.sign(head_delta) * min(abs(head_delta) * 0.35, 4.0)
        param = param_lookup[pipe_id]
        loss = FALLBACK_HEADLOSS_CALIBRATION * hazen_williams_headloss_m(
            flow,
            row["length_m"],
            row["diameter_mm"],
            param["adjusted_roughness_c"],
            param["minor_loss_k"],
        )
        pipe_rows.append(
            {
                **row,
                **param,
                "flow_lps": round(float(flow), 6),
                "headloss_m": round(float(loss), 6),
                "headloss_gradient_m_per_km": round(abs(float(loss)) / max(float(row["length_m"]), 1.0) * 1000.0, 6),
                "headloss_gradient": round(abs(float(loss)) / max(float(row["length_m"]), 1.0), 8),
                "from_hydraulic_grade_m": round(float(hgl.get(from_node, source_heads[root])), 6),
                "to_hydraulic_grade_m": round(float(hgl.get(to_node, source_heads[root])), 6),
                "valve_status": status_by_pipe.get(pipe_id, "open"),
            }
        )
    pipe_results = pd.DataFrame(pipe_rows)
    demand_node_results = node_results[node_results["node_type"].ne("reservoir")]
    pressure_violations = detect_pressure_violations(demand_node_results, threshold_m=min_pressure_head_m)
    pressure_stress = detect_aged_pipe_pressure_stress(pipe_results, node_results)
    pipe_results = pipe_results.merge(pipe_criticality[["pipe_id", "criticality_score"]], on="pipe_id", how="left")

    return {
        "node_results": node_results.sort_values("node_id").reset_index(drop=True),
        "pipe_results": pipe_results.sort_values("pipe_id").reset_index(drop=True),
        "pressure_violations": pressure_violations,
        "pressure_stress": pressure_stress,
        "aging_scores": aging_scores.sort_values("pipe_id").reset_index(drop=True),
        "pipe_params": pipe_params.sort_values("pipe_id").reset_index(drop=True),
        "metadata": {
            "engine": "fallback",
            "source_node": root,
            "min_pressure_head_m": float(min_pressure_head_m),
            "demand_multiplier": float(demand_multiplier),
            "source_head_delta_m": float(source_head_delta_m),
            "include_minor_losses": bool(include_minor_losses),
            "headloss_calibration": FALLBACK_HEADLOSS_CALIBRATION,
        },
    }


def run_hydraulic_simulation(
    data_dir: str | Path = "data/mock",
    tables: Mapping[str, pd.DataFrame] | None = None,
    min_pressure_head_m: float = 15.0,
    demand_multiplier: float = 1.0,
    source_head_delta_m: float = 0.0,
    valve_status_overrides: Mapping[str, str] | None = None,
    include_minor_losses: bool = True,
    prefer_wntr: bool = True,
) -> dict[str, pd.DataFrame | dict[str, object]]:
    """Run hydraulic simulation from loaded tables or a mock-data directory.

    WNTR is an optional dependency for this MVP. The current public contract
    always returns simple DataFrames; if WNTR is unavailable, the fallback path
    is used automatically.
    """

    loaded_tables = {name: frame.copy() for name, frame in tables.items()} if tables is not None else ensure_mock_data(data_dir)
    if prefer_wntr:
        try:
            import wntr  # noqa: F401  # type: ignore
        except ImportError:
            return run_fallback_simulation(
                loaded_tables,
                min_pressure_head_m=min_pressure_head_m,
                demand_multiplier=demand_multiplier,
                source_head_delta_m=source_head_delta_m,
                valve_status_overrides=valve_status_overrides,
                include_minor_losses=include_minor_losses,
            )

    return run_fallback_simulation(
        loaded_tables,
        min_pressure_head_m=min_pressure_head_m,
        demand_multiplier=demand_multiplier,
        source_head_delta_m=source_head_delta_m,
        valve_status_overrides=valve_status_overrides,
        include_minor_losses=include_minor_losses,
    )


def simulate(data_dir: str | Path = "data/mock", **kwargs) -> dict[str, pd.DataFrame | dict[str, object]]:
    """Convenience alias for UI/controller code."""

    return run_hydraulic_simulation(data_dir=data_dir, **kwargs)


def _pressure_status(pressure_head_m: float) -> str:
    value = float(pressure_head_m)
    if value < 10.0:
        return "critical"
    if value < 15.0:
        return "violation"
    if value < 20.0:
        return "marginal"
    if value < 60.0:
        return "normal"
    return "high-pressure stress"
