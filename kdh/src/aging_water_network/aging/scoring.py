"""Deterministic, explainable pipe aging score model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from aging_water_network.config import (
    CURRENT_YEAR,
    DEFAULT_AGING_WEIGHTS,
    DESIGN_LIFE_BY_MATERIAL,
    MATERIAL_RISK,
)
from aging_water_network.schemas import AgingScoreResult

COMPONENT_COLUMNS = [
    "age_component",
    "material_component",
    "repair_component",
    "leak_history_component",
    "geometry_component",
    "soil_component",
    "traffic_component",
    "pressure_stress_component",
    "topology_component",
]


def _clip01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    if isinstance(row, pd.Series):
        return row.get(key, default)
    if is_dataclass(row):
        return asdict(row).get(key, default)
    return getattr(row, key, default)


def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(float(value) for value in weights.values())
    if total <= 0:
        raise ValueError("Aging weights must have positive sum.")
    return {key: float(value) / total for key, value in weights.items()}


def age_component(pipe_row: Any, current_year: int = CURRENT_YEAR) -> float:
    material = str(_row_value(pipe_row, "material", "unknown"))
    install_year = int(_row_value(pipe_row, "install_year", current_year))
    design_life = float(DESIGN_LIFE_BY_MATERIAL.get(material, DESIGN_LIFE_BY_MATERIAL["unknown"]))
    return _clip01(max(current_year - install_year, 0) / design_life)


def material_component(pipe_row: Any) -> float:
    material = str(_row_value(pipe_row, "material", "unknown"))
    return _clip01(MATERIAL_RISK.get(material, MATERIAL_RISK["unknown"]))


def repair_component(pipe_row: Any) -> float:
    return _clip01(float(_row_value(pipe_row, "repair_count", 0) or 0) / 5.0)


def leak_history_component(pipe_row: Any) -> float:
    return _clip01(float(_row_value(pipe_row, "leak_history_count", 0) or 0) / 3.0)


def geometry_component(pipe_row: Any) -> float:
    bends = float(_row_value(pipe_row, "bend_count", 0) or 0)
    valves = float(_row_value(pipe_row, "valve_count", 0) or 0)
    return _clip01((bends + valves) / 8.0)


def soil_component(pipe_row: Any) -> float:
    soil_ph = float(_row_value(pipe_row, "soil_ph", 7.0) or 7.0)
    resistivity = float(_row_value(pipe_row, "soil_resistivity_ohm_cm", 3000.0) or 3000.0)

    if soil_ph < 6.0:
        ph_risk = 1.0
    elif soil_ph < 6.5:
        ph_risk = 0.75
    elif soil_ph < 7.5:
        ph_risk = 0.35
    else:
        ph_risk = 0.45

    if resistivity < 1000:
        resistivity_risk = 1.0
    elif resistivity < 2000:
        resistivity_risk = 0.75
    elif resistivity < 5000:
        resistivity_risk = 0.40
    else:
        resistivity_risk = 0.20

    return _clip01(0.5 * ph_risk + 0.5 * resistivity_risk)


def traffic_component(pipe_row: Any) -> float:
    return _clip01(float(_row_value(pipe_row, "traffic_load_index", 0.0) or 0.0))


def pressure_stress_component(pipe_row: Any) -> float:
    existing = _row_value(pipe_row, "pressure_stress_component", None)
    if existing is not None:
        return _clip01(existing)

    mean_pressure = _row_value(pipe_row, "mean_pressure_head_m", None)
    pressure_std = _row_value(pipe_row, "pressure_head_std_m", None)
    if mean_pressure is None and pressure_std is None:
        return 0.0

    mean_term = _clip01((float(mean_pressure or 0.0) - 30.0) / 40.0) * 0.5
    std_term = _clip01(float(pressure_std or 0.0) / 10.0) * 0.5
    return _clip01(mean_term + std_term)


def topology_component(pipe_row: Any) -> float:
    existing = _row_value(pipe_row, "topology_component", None)
    if existing is not None:
        return _clip01(existing)
    centrality = _row_value(pipe_row, "normalized_edge_betweenness_centrality", 0.0)
    return _clip01(float(centrality or 0.0))


def compute_pipe_aging_components(
    pipe_row: Any,
    current_year: int = CURRENT_YEAR,
) -> dict[str, float]:
    """Compute all component scores for a single pipe row."""
    return {
        "age_component": age_component(pipe_row, current_year),
        "material_component": material_component(pipe_row),
        "repair_component": repair_component(pipe_row),
        "leak_history_component": leak_history_component(pipe_row),
        "geometry_component": geometry_component(pipe_row),
        "soil_component": soil_component(pipe_row),
        "traffic_component": traffic_component(pipe_row),
        "pressure_stress_component": pressure_stress_component(pipe_row),
        "topology_component": topology_component(pipe_row),
    }


def compute_pipe_aging_score(
    pipe_row: Any,
    current_year: int = CURRENT_YEAR,
    weights: Mapping[str, float] | None = None,
) -> AgingScoreResult:
    """Compute the weighted 0-1 aging score for one pipe row."""
    normalized_weights = _normalize_weights(weights or DEFAULT_AGING_WEIGHTS)
    components = compute_pipe_aging_components(pipe_row, current_year)
    score = 0.0
    for weight_key, weight in normalized_weights.items():
        score += weight * components[f"{weight_key}_component"]

    return AgingScoreResult(
        pipe_id=str(_row_value(pipe_row, "pipe_id", "")),
        aging_score=_clip01(score),
        components=components,
    )


def compute_all_aging_scores(
    pipes_df: pd.DataFrame,
    current_year: int = CURRENT_YEAR,
    weights: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Compute aging scores for every pipe in a DataFrame."""
    rows = [
        compute_pipe_aging_score(pipe_row, current_year=current_year, weights=weights).to_row()
        for _, pipe_row in pipes_df.iterrows()
    ]
    columns = ["pipe_id", "aging_score", *COMPONENT_COLUMNS]
    return pd.DataFrame(rows, columns=columns)
