from __future__ import annotations

import pytest

from aging_water_network.data.mock_generator import build_mock_tables
from aging_water_network.visualization.network_plot import create_network_map


def test_network_map_renders_pipe_ids_at_pipe_midpoints_and_node_ids_at_nodes() -> None:
    tables = build_mock_tables(scenario="normal")
    nodes = tables["nodes"]
    pipes = tables["pipes"]
    first_pipe = pipes.iloc[0]
    pipe_id = str(first_pipe["pipe_id"])
    start = nodes.set_index("node_id").loc[first_pipe["from_node"]]
    end = nodes.set_index("node_id").loc[first_pipe["to_node"]]
    expected_mid_x = (float(start["x"]) + float(end["x"])) / 2.0
    expected_mid_y = (float(start["y"]) + float(end["y"])) / 2.0

    fig = create_network_map(nodes, pipes, selectable=True)
    pipe_label_trace = next(trace for trace in fig.data if trace.name == "pipe id labels")
    pipe_index = list(pipe_label_trace.text).index(pipe_id)
    annotation_texts = [item["text"] for item in fig.layout.annotations]

    assert pipe_label_trace.mode == "markers+text"
    assert pipe_label_trace.textposition == "middle center"
    assert list(pipe_label_trace.customdata)[pipe_index] == f"pipe:{pipe_id}"
    assert float(list(pipe_label_trace.x)[pipe_index]) == pytest.approx(expected_mid_x)
    assert float(list(pipe_label_trace.y)[pipe_index]) == pytest.approx(expected_mid_y)
    assert pipe_id in annotation_texts

    junction = nodes.loc[nodes["node_type"].astype(str).str.lower().eq("junction")].iloc[0]
    node_id = str(junction["node_id"])
    node_trace = next(trace for trace in fig.data if trace.name == "nodes")
    node_index = list(node_trace.text).index(node_id)

    assert node_trace.mode == "markers+text"
    assert node_trace.textposition == "middle center"
    assert list(node_trace.customdata)[node_index] == f"node:{node_id}"
    assert float(list(node_trace.x)[node_index]) == pytest.approx(float(junction["x"]))
    assert float(list(node_trace.y)[node_index]) == pytest.approx(float(junction["y"]))
    assert node_id in annotation_texts
