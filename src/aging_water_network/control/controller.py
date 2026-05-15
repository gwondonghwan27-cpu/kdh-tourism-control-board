"""Rule-based controller that ranks aging-aware hydraulic recommendations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from inspect import signature
from pathlib import Path
from typing import Any

import pandas as pd

from aging_water_network.config import DEFAULT_DATA_DIR, MIN_PRESSURE_HEAD_M
from aging_water_network.control.action_space import ControlAction, build_action_space
from aging_water_network.control.evaluator import (
    ActionEvaluation,
    evaluate_action,
    rank_evaluations,
)
from aging_water_network.data.loaders import ensure_mock_data
from aging_water_network.schemas import ControlRecommendation


Simulator = Callable[..., Any]


def _discover_hydraulic_simulator() -> Simulator | None:
    try:
        from aging_water_network.hydraulics.simulator import run_hydraulic_simulation

        return run_hydraulic_simulation
    except Exception:
        return None


def run_fallback_hydraulic_simulation(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    tables: Mapping[str, pd.DataFrame] | None = None,
    source_head_delta_m: float = 0.0,
    valve_status_overrides: Mapping[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Compatibility wrapper around the EPANET-formula local simulator."""

    from aging_water_network.hydraulics.simulator import run_fallback_simulation

    loaded = {name: frame.copy() for name, frame in tables.items()} if tables is not None else ensure_mock_data(data_dir)
    result = run_fallback_simulation(
        loaded,
        source_head_delta_m=source_head_delta_m,
        valve_status_overrides=valve_status_overrides,
    )
    nodes = result["node_results"].copy()
    pipes = result["pipe_results"].copy()
    node_pressures = nodes[["node_id", "pressure_head_m"]].copy()
    pipe_metrics = pipes[["pipe_id", "headloss_m"]].rename(columns={"headloss_m": "head_loss_m"})
    if not nodes.empty and not pipes.empty:
        pressure_map = nodes.set_index("node_id")["pressure_head_m"].to_dict()
        pipe_metrics["max_pressure_head_m"] = pipes.apply(
            lambda row: max(
                float(pressure_map.get(str(row["from_node"]), float("nan"))),
                float(pressure_map.get(str(row["to_node"]), float("nan"))),
            ),
            axis=1,
        )
    return {"node_pressures": node_pressures, "pipe_metrics": pipe_metrics}


def _run_simulator(
    simulator: Simulator | None,
    data_dir: str | Path,
    tables: Mapping[str, pd.DataFrame],
    action: ControlAction,
) -> Any:
    if simulator is None:
        return run_fallback_hydraulic_simulation(
            data_dir=data_dir,
            tables=tables,
            source_head_delta_m=action.source_head_delta_m,
            valve_status_overrides=action.valve_status_overrides,
        )
    kwargs = action.simulation_kwargs()
    try:
        parameters = signature(simulator).parameters
    except (TypeError, ValueError):
        parameters = {}
    supported_kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    if set(supported_kwargs) == set(kwargs):
        return simulator(data_dir=data_dir, tables=tables, **supported_kwargs)
    return run_fallback_hydraulic_simulation(
        data_dir=data_dir,
        tables=tables,
        source_head_delta_m=action.source_head_delta_m,
        valve_status_overrides=action.valve_status_overrides,
    )


def recommendation_from_evaluation(evaluation: ActionEvaluation) -> ControlRecommendation:
    action = evaluation.action
    risks = list(action.risks)
    if evaluation.pressure_violations:
        risks.append(f"Leaves {len(evaluation.pressure_violations)} demand nodes below 15 m.")
    if evaluation.aged_overpressure_pipes:
        risks.append(
            f"Overpressurizes {len(evaluation.aged_overpressure_pipes)} aged pipes above stress threshold."
        )

    affected_nodes = sorted(evaluation.pressure_violations)
    affected_pipes = sorted(evaluation.aged_overpressure_pipes)
    return ControlRecommendation(
        action_id=action.action_id,
        action_type=action.action_type,
        target_id=action.target_id,
        description=action.description,
        expected_effect=action.expected_effect,
        score=round(evaluation.score, 3),
        risks=risks,
        affected_nodes=affected_nodes,
        affected_pipes=affected_pipes,
    )


def rank_control_recommendations(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    tables: Mapping[str, pd.DataFrame] | None = None,
    simulator: Simulator | None = None,
    max_recommendations: int = 5,
    min_pressure_head_m: float = MIN_PRESSURE_HEAD_M,
) -> list[ControlRecommendation]:
    loaded = dict(tables) if tables is not None else ensure_mock_data(data_dir)
    hydraulic_simulator = simulator if simulator is not None else _discover_hydraulic_simulator()
    evaluations = [
        evaluate_action(
            action=action,
            simulation=_run_simulator(hydraulic_simulator, data_dir, loaded, action),
            tables=loaded,
            min_pressure_head_m=min_pressure_head_m,
        )
        for action in build_action_space(loaded)
    ]
    baseline = next((item for item in evaluations if item.action.action_id == "noop"), None)
    if baseline is not None and baseline.pressure_violations:
        pressure_recovery_actions = {
            "increase_pump_speed",
            "open_valve",
            "dispatch_inspection",
            "no_action",
        }
        evaluations = [
            item for item in evaluations if item.action.action_type in pressure_recovery_actions
        ]
    return [
        recommendation_from_evaluation(item)
        for item in rank_evaluations(evaluations)[:max_recommendations]
    ]
