"""Map aging scores to hydraulic pipe parameters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd

from aging_water_network.aging.risk import estimate_burst_probability, estimate_leak_probability
from aging_water_network.config import BASE_HW_C, MAX_C_DEGRADATION
from aging_water_network.schemas import HydraulicPipeParams


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


def base_hazen_williams_c(material: str) -> float:
    """Return the default Hazen-Williams C coefficient for a material."""
    return float(BASE_HW_C.get(str(material), BASE_HW_C["unknown"]))


def adjust_roughness_by_aging(
    material: str,
    aging_score: float,
    *,
    base_c: float | None = None,
    max_c_degradation: float = MAX_C_DEGRADATION,
) -> float:
    """Lower Hazen-Williams C as aging increases."""
    aging = _clip01(aging_score)
    degradation = max(0.0, min(float(max_c_degradation), 0.5))
    c_base = float(base_c) if base_c is not None else base_hazen_williams_c(material)
    return c_base * (1.0 - degradation * aging)


def estimate_minor_loss_k(
    aging_score: float,
    *,
    bend_count: int = 0,
    valve_minor_loss_k: float | Iterable[float] | None = None,
    base_k: float = 0.0,
) -> float:
    """Estimate total minor loss coefficient from bends, valves, and aging."""
    if valve_minor_loss_k is None:
        valve_k = 0.0
    elif isinstance(valve_minor_loss_k, Iterable) and not isinstance(
        valve_minor_loss_k, (str, bytes)
    ):
        valve_k = sum(float(value) for value in valve_minor_loss_k)
    else:
        valve_k = float(valve_minor_loss_k)

    return (
        float(base_k)
        + 0.2 * max(int(bend_count), 0)
        + valve_k
        + 1.5 * _clip01(aging_score)
    )


def hydraulic_params_for_pipe(
    pipe_row: Any,
    aging_score: float,
    *,
    valve_minor_loss_k: float | Iterable[float] | None = None,
    pressure_stress_component: float = 0.0,
    leak_history_component: float | None = None,
) -> HydraulicPipeParams:
    """Build the hydraulic parameter bundle for one pipe row."""
    material = str(_row_value(pipe_row, "material", "unknown"))
    pipe_id = str(_row_value(pipe_row, "pipe_id", ""))
    bend_count = int(_row_value(pipe_row, "bend_count", 0) or 0)
    if leak_history_component is None:
        leak_history_component = min(
            float(_row_value(pipe_row, "leak_history_count", 0) or 0) / 3.0,
            1.0,
        )

    base_c = base_hazen_williams_c(material)
    adjusted_c = adjust_roughness_by_aging(material, aging_score, base_c=base_c)
    return HydraulicPipeParams(
        pipe_id=pipe_id,
        base_roughness_c=base_c,
        adjusted_roughness_c=adjusted_c,
        minor_loss_k=estimate_minor_loss_k(
            aging_score,
            bend_count=bend_count,
            valve_minor_loss_k=valve_minor_loss_k,
        ),
        leak_probability=estimate_leak_probability(aging_score),
        burst_probability=estimate_burst_probability(
            aging_score,
            pressure_stress_component=pressure_stress_component,
            leak_history_component=leak_history_component,
        ),
    )


def compute_hydraulic_params(
    pipes_df: pd.DataFrame,
    aging_scores_df: pd.DataFrame,
    *,
    valves_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute hydraulic parameter rows for all pipes in a DataFrame."""
    score_by_pipe = aging_scores_df.set_index("pipe_id")
    valve_k_by_pipe: dict[str, list[float]] = {}
    if valves_df is not None and not valves_df.empty:
        valve_k_by_pipe = (
            valves_df.groupby("pipe_id")["minor_loss_k"]
            .apply(lambda values: [float(v) for v in values])
            .to_dict()
        )

    rows = []
    for _, pipe in pipes_df.iterrows():
        pipe_id = str(pipe["pipe_id"])
        score_row = score_by_pipe.loc[pipe_id]
        params = hydraulic_params_for_pipe(
            pipe,
            float(score_row["aging_score"]),
            valve_minor_loss_k=valve_k_by_pipe.get(pipe_id),
            pressure_stress_component=float(score_row.get("pressure_stress_component", 0.0)),
            leak_history_component=float(score_row.get("leak_history_component", 0.0)),
        )
        rows.append(
            {
                "pipe_id": params.pipe_id,
                "base_roughness_c": params.base_roughness_c,
                "adjusted_roughness_c": params.adjusted_roughness_c,
                "minor_loss_k": params.minor_loss_k,
                "leak_probability": params.leak_probability,
                "burst_probability": params.burst_probability,
            }
        )
    return pd.DataFrame(rows)
