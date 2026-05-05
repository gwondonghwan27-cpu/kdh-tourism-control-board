"""Hydraulic action evaluation with pressure and aging-aware stress penalties."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from aging_water_network.config import HIGH_PRESSURE_STRESS_M, MIN_PRESSURE_HEAD_M
from aging_water_network.control.action_space import ControlAction


@dataclass(frozen=True)
class ActionEvaluation:
    action: ControlAction
    score: float
    min_pressure_head_m: float
    pressure_violations: dict[str, float]
    aged_overpressure_pipes: dict[str, float]
    simulation: dict[str, Any] = field(default_factory=dict)


def _frame_from_simulation(simulation: Any, names: tuple[str, ...]) -> pd.DataFrame:
    if simulation is None:
        return pd.DataFrame()
    if isinstance(simulation, pd.DataFrame):
        return simulation.copy()
    if isinstance(simulation, Mapping):
        for name in names:
            value = simulation.get(name)
            if isinstance(value, pd.DataFrame):
                return value.copy()
            if isinstance(value, Mapping):
                return pd.DataFrame(
                    [
                        {"id": key, **val}
                        if isinstance(val, Mapping)
                        else {"id": key, "value": val}
                        for key, val in value.items()
                    ]
                )
    for name in names:
        value = getattr(simulation, name, None)
        if isinstance(value, pd.DataFrame):
            return value.copy()
        if isinstance(value, Mapping):
            return pd.DataFrame(
                [
                    {"id": key, **val} if isinstance(val, Mapping) else {"id": key, "value": val}
                    for key, val in value.items()
                ]
            )
    return pd.DataFrame()


def extract_node_pressures(simulation: Any) -> pd.DataFrame:
    """Normalize simulator output into ``node_id, pressure_head_m`` rows."""

    frame = _frame_from_simulation(
        simulation, ("node_pressures", "node_results", "pressures", "nodes")
    )
    if frame.empty:
        return pd.DataFrame(columns=["node_id", "pressure_head_m"])

    rename: dict[str, str] = {}
    for candidate in ("node_id", "node", "junction_id", "id"):
        if candidate in frame.columns:
            rename[candidate] = "node_id"
            break
    for candidate in ("pressure_head_m", "pressure_m", "head_m", "pressure", "value"):
        if candidate in frame.columns:
            rename[candidate] = "pressure_head_m"
            break
    frame = frame.rename(columns=rename)
    if {"node_id", "pressure_head_m"} - set(frame.columns):
        return pd.DataFrame(columns=["node_id", "pressure_head_m"])
    frame = frame[["node_id", "pressure_head_m"]].copy()
    frame["node_id"] = frame["node_id"].astype(str)
    frame["pressure_head_m"] = pd.to_numeric(frame["pressure_head_m"], errors="coerce")
    return frame.dropna(subset=["pressure_head_m"])


def extract_pipe_metrics(simulation: Any) -> pd.DataFrame:
    """Normalize simulator pipe output into optional pressure/head-loss metrics."""

    frame = _frame_from_simulation(simulation, ("pipe_metrics", "pipe_results", "pipes", "links"))
    if frame.empty:
        return pd.DataFrame(columns=["pipe_id"])
    rename: dict[str, str] = {}
    for candidate in ("pipe_id", "link_id", "id"):
        if candidate in frame.columns:
            rename[candidate] = "pipe_id"
            break
    return frame.rename(columns=rename)


def compute_pipe_stress(
    pipes: pd.DataFrame,
    node_pressures: pd.DataFrame,
    pipe_metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Estimate pressure stress per pipe from simulator pipe metrics or endpoint pressures."""

    if pipes.empty:
        return pd.DataFrame(columns=["pipe_id", "max_pressure_head_m"])
    stress = pipes[["pipe_id", "from_node", "to_node"]].copy()
    stress["pipe_id"] = stress["pipe_id"].astype(str)

    metrics = pipe_metrics if pipe_metrics is not None else pd.DataFrame()
    if not metrics.empty and "pipe_id" in metrics.columns:
        metric_cols = [
            col
            for col in ("max_pressure_head_m", "pressure_head_m", "pressure_m")
            if col in metrics.columns
        ]
        if metric_cols:
            metric = metrics[["pipe_id", metric_cols[0]]].rename(
                columns={metric_cols[0]: "max_pressure_head_m"}
            )
            metric["pipe_id"] = metric["pipe_id"].astype(str)
            stress = stress.merge(metric, on="pipe_id", how="left")
            stress["max_pressure_head_m"] = pd.to_numeric(
                stress["max_pressure_head_m"], errors="coerce"
            )
            return stress

    pressure_map = node_pressures.set_index("node_id")["pressure_head_m"].to_dict()
    stress["from_pressure_m"] = stress["from_node"].map(pressure_map)
    stress["to_pressure_m"] = stress["to_node"].map(pressure_map)
    stress["max_pressure_head_m"] = stress[["from_pressure_m", "to_pressure_m"]].max(axis=1)
    return stress


def aged_pipe_scores(pipes: pd.DataFrame) -> pd.Series:
    """Return package aging scores with a small local fallback for resilience."""

    if pipes.empty:
        return pd.Series(dtype=float)
    try:
        from aging_water_network.aging.scoring import compute_all_aging_scores

        scores = compute_all_aging_scores(pipes).set_index("pipe_id")["aging_score"]
        return pipes["pipe_id"].astype(str).map(scores).fillna(0.0).clip(0, 1)
    except Exception:
        pass

    age_component = ((2026 - pd.to_numeric(pipes["install_year"], errors="coerce")) / 70.0).clip(
        0, 1
    )
    repair_component = (
        pd.to_numeric(pipes.get("repair_count", 0), errors="coerce").fillna(0) / 5.0
    ).clip(0, 1)
    leak_component = (
        pd.to_numeric(pipes.get("leak_history_count", 0), errors="coerce").fillna(0) / 3.0
    ).clip(0, 1)
    material = (
        pipes.get("material", pd.Series("unknown", index=pipes.index)).astype(str).str.lower()
    )
    material_component = material.map(
        {
            "cast_iron": 0.85,
            "steel": 0.80,
            "concrete": 0.60,
            "ductile_iron": 0.45,
            "pvc": 0.25,
            "hdpe": 0.20,
        }
    ).fillna(0.55)
    return (
        0.35 * age_component
        + 0.25 * material_component
        + 0.20 * repair_component
        + 0.20 * leak_component
    ).clip(0, 1)


def evaluate_action(
    action: ControlAction,
    simulation: Any,
    tables: Mapping[str, pd.DataFrame],
    min_pressure_head_m: float = MIN_PRESSURE_HEAD_M,
    high_pressure_stress_m: float = HIGH_PRESSURE_STRESS_M,
) -> ActionEvaluation:
    node_pressures = extract_node_pressures(simulation)
    pipes = tables.get("pipes", pd.DataFrame())
    pipe_metrics = extract_pipe_metrics(simulation)
    pipe_stress = compute_pipe_stress(pipes, node_pressures, pipe_metrics)

    junctions = tables.get("nodes", pd.DataFrame())
    demand_nodes = set()
    if not junctions.empty and "node_type" in junctions.columns:
        demand_nodes = set(
            junctions.loc[
                junctions["node_type"].astype(str).str.lower().eq("junction"), "node_id"
            ].astype(str)
        )
    pressure_rows = (
        node_pressures[node_pressures["node_id"].isin(demand_nodes)]
        if demand_nodes
        else node_pressures
    )

    violations = {
        str(row.node_id): float(row.pressure_head_m)
        for row in pressure_rows.itertuples(index=False)
        if float(row.pressure_head_m) < min_pressure_head_m
    }
    min_pressure = (
        float(pressure_rows["pressure_head_m"].min()) if not pressure_rows.empty else float("nan")
    )

    overpressure: dict[str, float] = {}
    if not pipe_stress.empty:
        scores = aged_pipe_scores(pipes)
        stress = pipe_stress.copy()
        stress["aging_score"] = scores.to_numpy()
        stress["excess_m"] = (
            pd.to_numeric(stress["max_pressure_head_m"], errors="coerce") - high_pressure_stress_m
        )
        risky = stress[(stress["aging_score"] >= 0.55) & (stress["excess_m"] > 0)]
        overpressure = {
            str(row.pipe_id): float(row.excess_m) for row in risky.itertuples(index=False)
        }

    low_pressure_penalty = (
        sum((min_pressure_head_m - value) ** 2 for value in violations.values()) * 4.0
    )
    overpressure_penalty = sum(value * value for value in overpressure.values()) * 1.5
    adjustment_penalty = (
        abs(action.source_head_delta_m) * 0.6 + len(action.valve_status_overrides) * 1.2
    )
    reward = 30.0 if not violations else 0.0
    if action.source_head_delta_m < 0 and not violations:
        reward += min(abs(action.source_head_delta_m), 5.0) * 1.5
    score = reward - low_pressure_penalty - overpressure_penalty - adjustment_penalty

    return ActionEvaluation(
        action=action,
        score=float(score),
        min_pressure_head_m=min_pressure,
        pressure_violations=violations,
        aged_overpressure_pipes=overpressure,
        simulation={"node_pressures": node_pressures, "pipe_stress": pipe_stress},
    )


def rank_evaluations(evaluations: list[ActionEvaluation]) -> list[ActionEvaluation]:
    return sorted(evaluations, key=lambda item: item.score, reverse=True)
