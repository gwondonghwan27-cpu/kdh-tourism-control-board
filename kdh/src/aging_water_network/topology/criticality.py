"""Topology criticality scores for pipes and nodes."""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from aging_water_network.topology.graph_features import build_network_graph, compute_node_graph_features, compute_pipe_graph_features


def _normalize(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    max_value = float(values.max()) if len(values) else 0.0
    if max_value <= 0:
        return values * 0.0
    return values / max_value


def compute_pipe_criticality(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Score pipe criticality using edge centrality, demand served, and endpoint degree."""

    graph = build_network_graph(tables)
    pipe_features = compute_pipe_graph_features(graph)
    if pipe_features.empty:
        return pipe_features.assign(criticality_score=pd.Series(dtype=float))

    nodes = tables["nodes"][["node_id", "base_demand_lps"]]
    endpoint_demand = pipe_features.merge(nodes, left_on="from_node", right_on="node_id", how="left").rename(
        columns={"base_demand_lps": "from_demand_lps"}
    )
    endpoint_demand = endpoint_demand.merge(nodes, left_on="to_node", right_on="node_id", how="left").rename(
        columns={"base_demand_lps": "to_demand_lps"}
    )
    endpoint_demand["endpoint_demand_lps"] = endpoint_demand[["from_demand_lps", "to_demand_lps"]].fillna(0.0).sum(axis=1)
    endpoint_demand["criticality_score"] = (
        0.55 * _normalize(endpoint_demand["edge_betweenness_centrality"])
        + 0.30 * _normalize(endpoint_demand["endpoint_demand_lps"])
        + 0.15 * _normalize(endpoint_demand["degree_sum"])
    ).clip(0.0, 1.0)
    return endpoint_demand[
        [
            "pipe_id",
            "from_node",
            "to_node",
            "edge_betweenness_centrality",
            "endpoint_demand_lps",
            "degree_sum",
            "connects_articulation",
            "criticality_score",
        ]
    ].sort_values("pipe_id").reset_index(drop=True)


def compute_node_criticality(tables: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Score node criticality using graph centrality and local demand."""

    graph = build_network_graph(tables)
    node_features = compute_node_graph_features(graph)
    if node_features.empty:
        return node_features.assign(criticality_score=pd.Series(dtype=float))

    demand = tables["nodes"][["node_id", "base_demand_lps"]]
    result = node_features.merge(demand, on="node_id", how="left")
    result["criticality_score"] = (
        0.45 * _normalize(result["betweenness_centrality"])
        + 0.25 * _normalize(result["closeness_centrality"])
        + 0.20 * _normalize(result["base_demand_lps"])
        + 0.10 * result["is_articulation_point"].astype(float)
    ).clip(0.0, 1.0)
    return result.sort_values("node_id").reset_index(drop=True)


def compute_criticality(tables: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Return node and pipe criticality tables."""

    return {
        "node_criticality": compute_node_criticality(tables),
        "pipe_criticality": compute_pipe_criticality(tables),
    }
