from __future__ import annotations

import pandas as pd

from aging_water_network.data.mock_generator import build_mock_tables
from aging_water_network.hydraulics.dynamic import (
    aggregate_household_demands,
    apply_leak_demand,
    rank_leak_candidates,
    run_dynamic_demand_simulation,
)
from aging_water_network.hydraulics.simulator import run_hydraulic_simulation


def test_household_demands_aggregate_to_node_timeseries() -> None:
    tables = build_mock_tables(scenario="normal")

    node_demands = aggregate_household_demands(tables)

    assert not node_demands.empty
    assert {"timestamp", "node_id", "demand_lps"}.issubset(node_demands.columns)
    assert (node_demands["demand_lps"] >= 0).all()
    assert node_demands["timestamp"].nunique() == 96


def test_dynamic_simulation_finds_minimum_source_head_within_bounds() -> None:
    tables = build_mock_tables(scenario="normal")
    first_two_steps = (
        pd.to_datetime(tables["household_demand_timeseries"]["timestamp"])
        .drop_duplicates()
        .head(2)
        .tolist()
    )

    result = run_dynamic_demand_simulation(tables=tables, timestamps=first_two_steps)
    summary = result["dynamic_summary"]

    assert len(summary) == 2
    assert (summary["pressure_violations"] == 0).all()
    assert (summary["min_pressure_head_m"] >= 15.0).all()
    assert (summary["required_source_head_m"] <= 110.0).all()


def test_minor_loss_toggle_reduces_required_head_or_keeps_it_equal() -> None:
    tables = build_mock_tables(scenario="aging_headloss")
    timestamp = pd.to_datetime(tables["household_demand_timeseries"]["timestamp"]).iloc[0]

    without_minor = run_dynamic_demand_simulation(
        tables=tables,
        timestamps=[timestamp],
        include_minor_losses=False,
    )["dynamic_summary"].iloc[0]
    with_minor = run_dynamic_demand_simulation(
        tables=tables,
        timestamps=[timestamp],
        include_minor_losses=True,
    )["dynamic_summary"].iloc[0]

    assert without_minor["required_source_head_m"] <= with_minor["required_source_head_m"] + 0.1


def test_static_simulator_accepts_minor_loss_toggle() -> None:
    tables = build_mock_tables(scenario="normal")

    with_minor = run_hydraulic_simulation(tables=tables, include_minor_losses=True, prefer_wntr=False)
    without_minor = run_hydraulic_simulation(tables=tables, include_minor_losses=False, prefer_wntr=False)

    with_min = with_minor["node_results"].query("node_type != 'reservoir'")["pressure_head_m"].min()
    without_min = without_minor["node_results"].query("node_type != 'reservoir'")["pressure_head_m"].min()
    assert without_min >= with_min


def test_apply_leak_demand_increases_selected_pipe_to_node_demand() -> None:
    tables = build_mock_tables(scenario="normal")
    pipe = tables["pipes"].iloc[5]
    target_node = pipe["to_node"]
    before = float(
        tables["nodes"].loc[tables["nodes"]["node_id"].eq(target_node), "base_demand_lps"].iloc[0]
    )

    leaked, leak_info = apply_leak_demand(tables, "pipe", pipe["pipe_id"], 1.75)
    after = float(
        leaked["nodes"].loc[leaked["nodes"]["node_id"].eq(target_node), "base_demand_lps"].iloc[0]
    )

    assert leak_info["leak_pipe_id"] == pipe["pipe_id"]
    assert leak_info["leak_node_id"] == target_node
    assert after == before + 1.75


def test_rank_leak_candidates_uses_pressure_drop_signature() -> None:
    pipes = pd.DataFrame(
        [
            {"pipe_id": "P1", "from_node": "J1", "to_node": "J2"},
            {"pipe_id": "P2", "from_node": "J2", "to_node": "J3"},
        ]
    )
    baseline = pd.DataFrame(
        [
            {"node_id": "J1", "pressure_head_m": 30.0},
            {"node_id": "J2", "pressure_head_m": 30.0},
            {"node_id": "J3", "pressure_head_m": 30.0},
        ]
    )
    observed = pd.DataFrame(
        [
            {"node_id": "J1", "pressure_head_m": 29.8},
            {"node_id": "J2", "pressure_head_m": 24.0},
            {"node_id": "J3", "pressure_head_m": 23.0},
        ]
    )

    ranked = rank_leak_candidates(baseline, observed, pipes)

    assert ranked.iloc[0]["pipe_id"] == "P2"
    assert ranked.iloc[0]["leak_suspect_score"] > ranked.iloc[1]["leak_suspect_score"]
