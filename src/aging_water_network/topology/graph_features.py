"""Graph feature helpers for the mock water-network topology."""

from __future__ import annotations

from typing import Dict, Mapping

import networkx as nx
import pandas as pd


def _tables(tables_or_nodes: Mapping[str, pd.DataFrame] | pd.DataFrame, pipes: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    if isinstance(tables_or_nodes, Mapping):
        return tables_or_nodes["nodes"], tables_or_nodes["pipes"]
    if pipes is None:
        raise ValueError("pipes must be provided when nodes are passed directly")
    return tables_or_nodes, pipes


def build_network_graph(
    tables_or_nodes: Mapping[str, pd.DataFrame] | pd.DataFrame,
    pipes: pd.DataFrame | None = None,
) -> nx.Graph:
    """Build an undirected NetworkX graph from node and pipe tables."""

    nodes, pipe_table = _tables(tables_or_nodes, pipes)
    graph = nx.Graph()
    for row in nodes.to_dict("records"):
        node_id = str(row["node_id"])
        graph.add_node(node_id, **row)

    for row in pipe_table.to_dict("records"):
        length = float(row.get("length_m", 1.0))
        diameter = float(row.get("diameter_mm", 1.0))
        attrs = dict(row)
        graph.add_edge(
            str(row["from_node"]),
            str(row["to_node"]),
            weight=length,
            hydraulic_weight=length / max(diameter, 1.0) ** 4.871,
            **attrs,
        )
    return graph


def compute_node_graph_features(graph: nx.Graph) -> pd.DataFrame:
    """Return deterministic node-level topology features."""

    if graph.number_of_nodes() == 0:
        return pd.DataFrame(
            columns=[
                "node_id",
                "degree",
                "betweenness_centrality",
                "closeness_centrality",
                "is_articulation_point",
            ]
        )

    betweenness = nx.betweenness_centrality(graph, weight="weight", normalized=True)
    closeness = nx.closeness_centrality(graph, distance="weight")
    articulation_points = set(nx.articulation_points(graph))
    rows = []
    for node_id in sorted(graph.nodes):
        rows.append(
            {
                "node_id": node_id,
                "degree": int(graph.degree[node_id]),
                "betweenness_centrality": float(betweenness.get(node_id, 0.0)),
                "closeness_centrality": float(closeness.get(node_id, 0.0)),
                "is_articulation_point": bool(node_id in articulation_points),
            }
        )
    return pd.DataFrame(rows)


def compute_pipe_graph_features(graph: nx.Graph) -> pd.DataFrame:
    """Return pipe-level topology features keyed by ``pipe_id``."""

    edge_between = nx.edge_betweenness_centrality(graph, weight="weight", normalized=True)
    rows = []
    for from_node, to_node, data in graph.edges(data=True):
        rows.append(
            {
                "pipe_id": data["pipe_id"],
                "from_node": from_node,
                "to_node": to_node,
                "edge_betweenness_centrality": float(edge_between.get((from_node, to_node), edge_between.get((to_node, from_node), 0.0))),
                "connects_articulation": False,
                "degree_sum": int(graph.degree[from_node] + graph.degree[to_node]),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "pipe_id",
                "from_node",
                "to_node",
                "edge_betweenness_centrality",
                "connects_articulation",
                "degree_sum",
            ]
        )

    articulation_points = set(nx.articulation_points(graph))
    features = pd.DataFrame(rows)
    features["connects_articulation"] = features["from_node"].isin(articulation_points) | features["to_node"].isin(articulation_points)
    return features.sort_values("pipe_id").reset_index(drop=True)


def compute_graph_features(
    tables_or_nodes: Mapping[str, pd.DataFrame] | pd.DataFrame,
    pipes: pd.DataFrame | None = None,
) -> Dict[str, pd.DataFrame]:
    """Compute graph, node, and pipe feature tables in one call."""

    graph = build_network_graph(tables_or_nodes, pipes)
    return {
        "graph": graph,
        "node_features": compute_node_graph_features(graph),
        "pipe_features": compute_pipe_graph_features(graph),
    }
