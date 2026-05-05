from __future__ import annotations

import pandas as pd
import pytest

from aging_water_network.data.mock_generator import build_mock_tables
from aging_water_network.hydraulics.dynamic import aggregate_household_demands
from aging_water_network.hydraulics.live import (
    DemandOverride,
    LiveScenarioState,
    PipeOverride,
    compute_live_snapshot,
)
from app.streamlit_app import parse_clicked_object


@pytest.fixture()
def live_inputs() -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp]:
    tables = build_mock_tables(scenario="normal")
    node_demands = aggregate_household_demands(tables)
    timestamp = pd.Timestamp(node_demands["timestamp"].iloc[0])
    return tables, node_demands, timestamp


def _state(timestamp: pd.Timestamp, **kwargs: object) -> LiveScenarioState:
    defaults: dict[str, object] = {
        "timestamp": timestamp,
        "pressure_mode": "manual",
        "manual_source_head_m": 64.0,
        "leak_enabled": False,
        "include_minor_losses": False,
    }
    defaults.update(kwargs)
    return LiveScenarioState(**defaults)


def _pipe_row(frame: pd.DataFrame, pipe_id: str) -> pd.Series:
    return frame.loc[frame["pipe_id"].astype(str).eq(pipe_id)].iloc[0]


def _demand_nodes(pressure: pd.DataFrame) -> pd.DataFrame:
    return pressure.loc[pressure["node_type"].astype(str).str.lower().ne("reservoir")]


def test_pipe_session_override_changes_aging_roughness_headloss_and_pressure(
    live_inputs: tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp],
) -> None:
    tables, node_demands, timestamp = live_inputs
    pipe_id = "P14"

    baseline = compute_live_snapshot(tables, node_demands, _state(timestamp))
    overridden = compute_live_snapshot(
        tables,
        node_demands,
        _state(
            timestamp,
            pipe_overrides={
                pipe_id: PipeOverride(
                    install_year=1930,
                    repair_count=6,
                    leak_history_count=3,
                )
            },
        ),
    )

    baseline_pipe = _pipe_row(baseline.aging, pipe_id)
    overridden_pipe = _pipe_row(overridden.aging, pipe_id)
    baseline_headloss = _pipe_row(baseline.headloss, pipe_id)
    overridden_headloss = _pipe_row(overridden.headloss, pipe_id)

    assert overridden_pipe["install_year"] == 1930
    assert overridden_pipe["repair_count"] == 6
    assert overridden_pipe["leak_history_count"] == 3
    assert overridden_pipe["aging_score"] > baseline_pipe["aging_score"]
    assert overridden_pipe["adjusted_roughness_c"] < baseline_pipe["adjusted_roughness_c"]
    assert overridden_headloss["headloss_m"] > baseline_headloss["headloss_m"]
    assert overridden.summary["min_pressure_head_m"] < baseline.summary["min_pressure_head_m"]


def test_leak_injection_is_reflected_in_info_tables_and_candidates(
    live_inputs: tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp],
) -> None:
    tables, node_demands, timestamp = live_inputs
    target_pipe = "P14"
    target_node = str(_pipe_row(tables["pipes"], target_pipe)["to_node"])

    snapshot = compute_live_snapshot(
        tables,
        node_demands,
        _state(
            timestamp,
            leak_enabled=True,
            leak_target_type="pipe",
            leak_target_id=target_pipe,
            leak_demand_lps=3.5,
        ),
    )

    no_leak_demand = float(
        snapshot.no_leak_tables["nodes"]
        .loc[
            snapshot.no_leak_tables["nodes"]["node_id"].astype(str).eq(target_node),
            "base_demand_lps",
        ]
        .iloc[0]
    )
    live_demand = float(
        snapshot.tables["nodes"]
        .loc[snapshot.tables["nodes"]["node_id"].astype(str).eq(target_node), "base_demand_lps"]
        .iloc[0]
    )
    touches_leak_node = snapshot.leak_candidates["from_node"].astype(str).eq(
        target_node
    ) | snapshot.leak_candidates["to_node"].astype(str).eq(target_node)

    assert snapshot.leak_info == {
        "leak_node_id": target_node,
        "leak_pipe_id": target_pipe,
        "leak_demand_lps": 3.5,
    }
    assert live_demand == pytest.approx(no_leak_demand + 3.5)
    assert not snapshot.leak_candidates.empty
    assert snapshot.leak_candidates["mean_pressure_drop_m"].max() > 0.0
    assert target_pipe in set(snapshot.leak_candidates["pipe_id"].astype(str))
    assert snapshot.leak_candidates.loc[
        snapshot.leak_candidates["pipe_id"].astype(str).eq(target_pipe),
        "is_injected_leak",
    ].any()
    assert touches_leak_node.any()


def test_no_leak_state_has_no_suspect_candidates(
    live_inputs: tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp],
) -> None:
    tables, node_demands, timestamp = live_inputs

    snapshot = compute_live_snapshot(
        tables,
        node_demands,
        _state(timestamp, leak_enabled=False, leak_demand_lps=0.0),
    )

    assert snapshot.leak_info["leak_demand_lps"] == 0.0
    assert snapshot.leak_candidates.empty


def test_auto_source_head_has_zero_low_pressure_demand_nodes(
    live_inputs: tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp],
) -> None:
    tables, node_demands, timestamp = live_inputs

    snapshot = compute_live_snapshot(
        tables,
        node_demands,
        LiveScenarioState(timestamp=timestamp, pressure_mode="auto", leak_enabled=False),
    )
    demand_nodes = _demand_nodes(snapshot.pressure)

    assert snapshot.summary["pressure_violations"] == 0
    assert (demand_nodes["pressure_head_m"] < 15.0).sum() == 0
    assert snapshot.summary["within_hydraulic_bounds"] is True


def test_manual_low_vs_high_source_head_changes_pressure_violations(
    live_inputs: tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp],
) -> None:
    tables, node_demands, timestamp = live_inputs

    low_head = compute_live_snapshot(
        tables,
        node_demands,
        _state(timestamp, manual_source_head_m=40.0),
    )
    high_head = compute_live_snapshot(
        tables,
        node_demands,
        _state(timestamp, manual_source_head_m=60.0),
    )

    assert low_head.summary["pressure_violations"] > 0
    assert high_head.summary["pressure_violations"] == 0
    assert low_head.summary["min_pressure_head_m"] < high_head.summary["min_pressure_head_m"]


def test_compute_live_snapshot_does_not_mutate_baseline_tables(
    live_inputs: tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.Timestamp],
) -> None:
    tables, node_demands, timestamp = live_inputs
    baseline_tables = {name: frame.copy(deep=True) for name, frame in tables.items()}
    baseline_node_demands = node_demands.copy(deep=True)

    compute_live_snapshot(
        tables,
        node_demands,
        _state(
            timestamp,
            global_demand_multiplier=1.25,
            demand_overrides={"J16": DemandOverride(multiplier=1.4, extra_demand_lps=0.75)},
            leak_enabled=True,
            leak_target_type="pipe",
            leak_target_id="P14",
            leak_demand_lps=4.0,
            pipe_overrides={
                "P14": PipeOverride(
                    material="cast_iron",
                    install_year=1930,
                    repair_count=6,
                    leak_history_count=3,
                    diameter_mm=120.0,
                    aging_score_override=0.95,
                )
            },
        ),
    )

    for name, expected in baseline_tables.items():
        pd.testing.assert_frame_equal(tables[name], expected)
    pd.testing.assert_frame_equal(node_demands, baseline_node_demands)


def test_plotly_click_parser_recovers_customdata_from_curve_and_point() -> None:
    class Trace:
        customdata = ["pipe:P1", "node:J2"]

    class Figure:
        data = [Trace()]

    event = [{"curveNumber": 0, "pointNumber": 1}]

    assert parse_clicked_object(event, Figure()) == ("node", "J2")
