"""Rule-based controller that ranks aging-aware hydraulic recommendations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from heapq import heappop, heappush
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


def _pipe_loss_factor(pipe: pd.Series, valve_status: str | None = None) -> float:
    diameter = max(float(pipe["diameter_mm"]), 1.0)
    length = max(float(pipe["length_m"]), 1.0)
    age = max(0.0, 2026 - float(pipe["install_year"]))
    material = str(pipe.get("material", "unknown")).lower()
    material_factor = {
        "cast_iron": 1.45,
        "steel": 1.32,
        "concrete": 1.20,
        "ductile_iron": 1.05,
        "pvc": 0.85,
        "hdpe": 0.82,
    }.get(material, 1.15)
    history_factor = (
        1.0
        + 0.10 * float(pipe.get("repair_count", 0))
        + 0.15 * float(pipe.get("leak_history_count", 0))
    )
    valve_factor = {"open": 1.0, "partially_open": 2.4, "closed": 8.0}.get(
        str(valve_status or "open").lower(), 1.0
    )
    return 1.15 * (
        (length / 100.0)
        * (300.0 / diameter) ** 1.8
        * (1.0 + age / 140.0)
        * material_factor
        * history_factor
        * valve_factor
    )


def run_fallback_hydraulic_simulation(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    tables: Mapping[str, pd.DataFrame] | None = None,
    source_head_delta_m: float = 0.0,
    valve_status_overrides: Mapping[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Deterministic pressure approximation used when the WNTR worker API is absent."""

    loaded = dict(tables) if tables is not None else ensure_mock_data(data_dir)
    nodes = loaded["nodes"]
    pipes = loaded["pipes"]
    valves = loaded.get("valves", pd.DataFrame())
    reservoirs = loaded.get("reservoirs", pd.DataFrame())
    pumps = loaded.get("pumps", pd.DataFrame())
    overrides = dict(valve_status_overrides or {})

    valve_by_pipe = {}
    if not valves.empty:
        for valve in valves.to_dict("records"):
            status = overrides.get(str(valve["valve_id"]), str(valve["status"]))
            valve_by_pipe[str(valve["pipe_id"])] = status

    graph: dict[str, list[tuple[str, float, str]]] = {
        str(node_id): [] for node_id in nodes["node_id"].astype(str)
    }
    for pipe in pipes.to_dict("records"):
        loss = _pipe_loss_factor(pd.Series(pipe), valve_by_pipe.get(str(pipe["pipe_id"])))
        from_node = str(pipe["from_node"])
        to_node = str(pipe["to_node"])
        pipe_id = str(pipe["pipe_id"])
        graph.setdefault(from_node, []).append((to_node, loss, pipe_id))
        graph.setdefault(to_node, []).append((from_node, loss, pipe_id))

    reservoir_node = (
        str(reservoirs.iloc[0]["node_id"])
        if not reservoirs.empty
        else str(nodes.iloc[0]["node_id"])
    )
    source_head = float(reservoirs.iloc[0]["head_m"]) if not reservoirs.empty else 70.0
    if not pumps.empty:
        source_head += float(pumps.iloc[0].get("base_head_gain_m", 0.0)) * float(
            pumps.iloc[0].get("speed_multiplier", 1.0)
        )
    source_head += float(source_head_delta_m)
    distance_loss = _shortest_weighted_distances(graph, reservoir_node)

    demand_map = nodes.set_index("node_id")["base_demand_lps"].to_dict()
    elevation_map = nodes.set_index("node_id")["elevation_m"].to_dict()
    rows = []
    for node_id in nodes["node_id"].astype(str):
        node_loss = distance_loss.get(node_id, float("inf"))
        demand_penalty = 0.9 * float(demand_map.get(node_id, 0.0))
        elevation_penalty = (
            max(
                0.0,
                float(elevation_map.get(node_id, 0.0))
                - float(elevation_map.get(reservoir_node, 0.0)),
            )
            * 0.15
        )
        pressure = source_head - node_loss - demand_penalty - elevation_penalty
        rows.append({"node_id": node_id, "pressure_head_m": round(float(pressure), 3)})

    node_pressures = pd.DataFrame(rows)
    pipe_rows = []
    pressure_map = node_pressures.set_index("node_id")["pressure_head_m"].to_dict()
    for pipe in pipes.to_dict("records"):
        p1 = float(pressure_map[str(pipe["from_node"])])
        p2 = float(pressure_map[str(pipe["to_node"])])
        pipe_rows.append(
            {
                "pipe_id": str(pipe["pipe_id"]),
                "max_pressure_head_m": max(p1, p2),
                "head_loss_m": abs(p1 - p2),
            }
        )
    return {"node_pressures": node_pressures, "pipe_metrics": pd.DataFrame(pipe_rows)}


def _shortest_weighted_distances(
    graph: Mapping[str, list[tuple[str, float, str]]],
    source_node: str,
) -> dict[str, float]:
    distances = {source_node: 0.0}
    queue: list[tuple[float, str]] = [(0.0, source_node)]
    while queue:
        current_distance, node_id = heappop(queue)
        if current_distance > distances.get(node_id, float("inf")):
            continue
        for next_node, weight, _pipe_id in graph.get(node_id, []):
            candidate = current_distance + float(weight)
            if candidate < distances.get(next_node, float("inf")):
                distances[next_node] = candidate
                heappush(queue, (candidate, next_node))
    return distances


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
