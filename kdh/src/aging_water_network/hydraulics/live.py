"""Live-control state and snapshot calculation for the Streamlit simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from aging_water_network.aging.roughness import compute_hydraulic_params
from aging_water_network.aging.scoring import compute_all_aging_scores
from aging_water_network.config import (
    HEAD_LOSS_GRADIENT_CRITICAL,
    HEAD_LOSS_GRADIENT_WARNING,
    HIGH_PRESSURE_STRESS_M,
    MIN_PRESSURE_HEAD_M,
)
from aging_water_network.hydraulics.dynamic import (
    apply_leak_demand,
    build_time_step_tables,
    find_minimum_source_head,
    rank_leak_candidates,
)
from aging_water_network.hydraulics.simulator import run_hydraulic_simulation


@dataclass(frozen=True)
class DemandOverride:
    multiplier: float = 1.0
    extra_demand_lps: float = 0.0


@dataclass(frozen=True)
class PipeOverride:
    material: str | None = None
    install_year: int | None = None
    repair_count: int | None = None
    leak_history_count: int | None = None
    diameter_mm: float | None = None
    aging_score_override: float | None = None


@dataclass(frozen=True)
class LiveScenarioState:
    timestamp: pd.Timestamp
    global_demand_multiplier: float = 1.0
    demand_overrides: dict[str, DemandOverride] = field(default_factory=dict)
    pressure_mode: str = "auto"
    manual_source_head_m: float = 64.0
    include_minor_losses: bool = False
    leak_enabled: bool = True
    leak_target_type: str = "pipe"
    leak_target_id: str = "P14"
    leak_demand_lps: float = 2.0
    pipe_overrides: dict[str, PipeOverride] = field(default_factory=dict)
    selected_pipe_id: str | None = None
    selected_node_id: str | None = None


@dataclass(frozen=True)
class LiveSimulationSnapshot:
    state: LiveScenarioState
    tables: dict[str, pd.DataFrame]
    no_leak_tables: dict[str, pd.DataFrame]
    operating_tables: dict[str, pd.DataFrame]
    node_demands: pd.DataFrame
    aging: pd.DataFrame
    pipe_params: pd.DataFrame
    pressure: pd.DataFrame
    headloss: pd.DataFrame
    recommendations: pd.DataFrame
    leak_candidates: pd.DataFrame
    leak_info: dict[str, str | float]
    summary: dict[str, Any]
    elapsed_ms: float = 0.0


def compute_live_snapshot(
    base_tables: Mapping[str, pd.DataFrame],
    node_demand_timeseries: pd.DataFrame,
    state: LiveScenarioState,
) -> LiveSimulationSnapshot:
    """Compute a single interactive hydraulic snapshot without mutating base tables."""

    edited_tables = apply_pipe_overrides(base_tables, state.pipe_overrides)
    node_demands = node_demands_for_timestamp(
        node_demand_timeseries,
        state.timestamp,
        state.global_demand_multiplier,
        state.demand_overrides,
    )
    no_leak_tables = build_time_step_tables(edited_tables, node_demands)
    leak_info: dict[str, str | float] = {
        "leak_node_id": "",
        "leak_pipe_id": "",
        "leak_demand_lps": 0.0,
    }
    live_tables = no_leak_tables
    if state.leak_enabled and state.leak_demand_lps > 0:
        live_tables, leak_info = apply_leak_demand(
            no_leak_tables,
            target_type=state.leak_target_type,
            target_id=state.leak_target_id,
            leak_demand_lps=state.leak_demand_lps,
        )

    if state.pressure_mode == "manual":
        base_source = _base_source_head(live_tables)
        source_delta = state.manual_source_head_m - base_source
        live_result = run_hydraulic_simulation(
            tables=live_tables,
            source_head_delta_m=source_delta,
            include_minor_losses=state.include_minor_losses,
            prefer_wntr=False,
        )
        demand_nodes = _demand_nodes(live_result["node_results"])
        summary = _manual_summary(
            demand_nodes,
            required_source_head_m=state.manual_source_head_m,
            source_delta_m=source_delta,
        )
    else:
        search = find_minimum_source_head(
            live_tables,
            include_minor_losses=state.include_minor_losses,
        )
        live_result = search["result"]
        assert isinstance(live_result, dict)
        summary = dict(search["summary"])
        source_delta = float(summary["source_head_delta_m"])

    baseline_result = run_hydraulic_simulation(
        tables=no_leak_tables,
        source_head_delta_m=source_delta,
        include_minor_losses=state.include_minor_losses,
        prefer_wntr=False,
    )
    aging = compute_live_aging(live_tables["pipes"])
    pipe_params = compute_hydraulic_params(live_tables["pipes"], aging, valves_df=live_tables.get("valves"))
    pressure = normalize_pressure_results(live_result["node_results"])
    headloss = normalize_headloss_results(live_result["pipe_results"])
    aging_context = merge_pipe_context(live_tables["pipes"], aging, pipe_params)
    leak_candidates = live_leak_candidates(
        baseline_result["node_results"],
        live_result["node_results"],
        live_tables["pipes"],
        aging,
        leak_info,
    )

    operating_tables = tables_with_source_delta(live_tables, source_delta)
    recommendations = build_live_recommendations(
        operating_tables,
        aging_context,
        pressure,
        headloss,
        summary,
    )

    return LiveSimulationSnapshot(
        state=state,
        tables=live_tables,
        no_leak_tables=no_leak_tables,
        operating_tables=operating_tables,
        node_demands=node_demands,
        aging=aging_context,
        pipe_params=pipe_params,
        pressure=pressure,
        headloss=headloss,
        recommendations=recommendations,
        leak_candidates=leak_candidates,
        leak_info=leak_info,
        summary=summary,
    )


def apply_pipe_overrides(
    tables: Mapping[str, pd.DataFrame],
    pipe_overrides: Mapping[str, PipeOverride],
) -> dict[str, pd.DataFrame]:
    copied = {name: frame.copy(deep=True) for name, frame in tables.items()}
    pipes = copied["pipes"].copy()
    for pipe_id, override in pipe_overrides.items():
        mask = pipes["pipe_id"].astype(str).eq(str(pipe_id))
        if not mask.any():
            continue
        values = {
            "material": override.material,
            "install_year": override.install_year,
            "repair_count": override.repair_count,
            "leak_history_count": override.leak_history_count,
            "diameter_mm": override.diameter_mm,
            "aging_score_override": override.aging_score_override,
        }
        for column, value in values.items():
            if value is not None:
                pipes.loc[mask, column] = value
    copied["pipes"] = pipes
    return copied


def compute_live_aging(pipes: pd.DataFrame) -> pd.DataFrame:
    aging = compute_all_aging_scores(pipes)
    if "aging_score_override" not in pipes.columns:
        return aging
    override = pipes[["pipe_id", "aging_score_override"]].copy()
    override["aging_score_override"] = pd.to_numeric(
        override["aging_score_override"], errors="coerce"
    )
    aging = aging.merge(override, on="pipe_id", how="left")
    mask = aging["aging_score_override"].notna()
    aging.loc[mask, "aging_score"] = aging.loc[mask, "aging_score_override"].clip(0.0, 1.0)
    return aging.drop(columns=["aging_score_override"])


def node_demands_for_timestamp(
    node_demand_timeseries: pd.DataFrame,
    timestamp: pd.Timestamp,
    global_multiplier: float,
    demand_overrides: Mapping[str, DemandOverride],
) -> pd.DataFrame:
    frame = node_demand_timeseries[
        pd.to_datetime(node_demand_timeseries["timestamp"]).eq(pd.Timestamp(timestamp))
    ][["node_id", "demand_lps"]].copy()
    frame["demand_lps"] = pd.to_numeric(frame["demand_lps"], errors="coerce").fillna(0.0)
    frame["demand_lps"] *= max(float(global_multiplier), 0.0)
    for node_id, override in demand_overrides.items():
        mask = frame["node_id"].astype(str).eq(str(node_id))
        if mask.any():
            frame.loc[mask, "demand_lps"] = (
                frame.loc[mask, "demand_lps"] * max(float(override.multiplier), 0.0)
                + max(float(override.extra_demand_lps), 0.0)
            )
    frame.insert(0, "timestamp", pd.Timestamp(timestamp))
    return frame


def tables_with_source_delta(
    tables: Mapping[str, pd.DataFrame],
    source_delta_m: float,
) -> dict[str, pd.DataFrame]:
    copied = {name: frame.copy(deep=True) for name, frame in tables.items()}
    if "reservoirs" in copied and not copied["reservoirs"].empty:
        copied["reservoirs"]["head_m"] = pd.to_numeric(
            copied["reservoirs"]["head_m"], errors="coerce"
        ).fillna(0.0) + float(source_delta_m)
    return copied


def merge_pipe_context(
    pipes: pd.DataFrame,
    aging: pd.DataFrame,
    pipe_params: pd.DataFrame,
) -> pd.DataFrame:
    frame = pipes.merge(aging, on="pipe_id", how="left")
    param_cols = [
        "pipe_id",
        "base_roughness_c",
        "adjusted_roughness_c",
        "minor_loss_k",
        "leak_probability",
        "burst_probability",
    ]
    existing = [column for column in param_cols if column in pipe_params.columns]
    return frame.merge(pipe_params[existing], on="pipe_id", how="left")


def normalize_pressure_results(node_results: pd.DataFrame) -> pd.DataFrame:
    frame = node_results.copy()
    if "pressure_status" not in frame.columns:
        frame["pressure_status"] = frame["pressure_head_m"].map(_pressure_status)
    return frame


def normalize_headloss_results(pipe_results: pd.DataFrame) -> pd.DataFrame:
    frame = pipe_results.copy()
    if "head_loss_m" not in frame.columns and "headloss_m" in frame.columns:
        frame["head_loss_m"] = frame["headloss_m"]
    if "head_loss_gradient" not in frame.columns and "headloss_gradient_m_per_km" in frame.columns:
        frame["head_loss_gradient"] = frame["headloss_gradient_m_per_km"] / 1000.0
    return frame


def recommendations_to_frame(recommendations: list[Any]) -> pd.DataFrame:
    rows = []
    for item in recommendations:
        row = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        for column in ("affected_nodes", "affected_pipes", "risks"):
            if isinstance(row.get(column), list):
                row[column] = ", ".join(str(value) for value in row[column])
        rows.append(row)
    return pd.DataFrame(rows)


def live_leak_candidates(
    baseline_node_results: pd.DataFrame,
    leak_node_results: pd.DataFrame,
    pipes: pd.DataFrame,
    aging_scores: pd.DataFrame,
    leak_info: Mapping[str, str | float],
    top_n: int = 8,
) -> pd.DataFrame:
    columns = [
        "pipe_id",
        "from_node",
        "to_node",
        "mean_pressure_drop_m",
        "aging_score",
        "drop_score",
        "leak_suspect_score",
        "is_injected_leak",
    ]
    if float(leak_info.get("leak_demand_lps", 0.0) or 0.0) <= 0.0:
        return pd.DataFrame(columns=columns)

    full_rank = rank_leak_candidates(
        baseline_node_results,
        leak_node_results,
        pipes,
        aging_scores=aging_scores,
        top_n=max(top_n, len(pipes)),
    )
    if full_rank.empty:
        return pd.DataFrame(columns=columns)

    full_rank["is_injected_leak"] = False
    leak_pipe_id = str(leak_info.get("leak_pipe_id", "") or "")
    if leak_pipe_id:
        full_rank.loc[full_rank["pipe_id"].astype(str).eq(leak_pipe_id), "is_injected_leak"] = True

    display = full_rank.head(top_n).copy()
    if leak_pipe_id and not display["pipe_id"].astype(str).eq(leak_pipe_id).any():
        injected = full_rank[full_rank["pipe_id"].astype(str).eq(leak_pipe_id)]
        if not injected.empty:
            display = pd.concat([display, injected.head(1)], ignore_index=True)

    display = display.drop_duplicates("pipe_id", keep="first")
    if "is_injected_leak" not in display.columns:
        display["is_injected_leak"] = False
    return display[columns].reset_index(drop=True)


def build_live_recommendations(
    tables: Mapping[str, pd.DataFrame],
    aging: pd.DataFrame,
    pressure: pd.DataFrame,
    headloss: pd.DataFrame,
    summary: Mapping[str, Any],
) -> pd.DataFrame:
    low_nodes = pressure.loc[
        pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M, "node_id"
    ].astype(str).tolist()
    marginal_nodes = pressure.loc[
        pressure["pressure_head_m"].between(MIN_PRESSURE_HEAD_M, 20.0, inclusive="left"),
        "node_id",
    ].astype(str).tolist()
    high_nodes = pressure.loc[
        pressure["pressure_head_m"] > HIGH_PRESSURE_STRESS_M, "node_id"
    ].astype(str).tolist()
    aged_pipes = aging.loc[aging["aging_score"] >= 0.70, "pipe_id"].astype(str).tolist()

    severe_headloss: list[str] = []
    warning_headloss: list[str] = []
    if not headloss.empty and "head_loss_gradient" in headloss.columns:
        gradients = pd.to_numeric(headloss["head_loss_gradient"], errors="coerce").fillna(0.0)
        severe_headloss = headloss.loc[
            gradients >= HEAD_LOSS_GRADIENT_CRITICAL, "pipe_id"
        ].astype(str).tolist()
        warning_headloss = headloss.loc[
            gradients >= HEAD_LOSS_GRADIENT_WARNING, "pipe_id"
        ].astype(str).tolist()

    rows: list[dict[str, Any]] = []
    min_pressure = float(summary.get("min_pressure_head_m", pressure["pressure_head_m"].min()))
    if low_nodes:
        needed_gain = max(MIN_PRESSURE_HEAD_M - min_pressure + 0.5, 0.5)
        rows.append(
            _recommendation_row(
                "L1",
                "increase_pump_speed",
                "source",
                f"Increase source head by about {needed_gain:.1f} m and re-check aged-pipe stress.",
                f"Targets {len(low_nodes)} nodes below {MIN_PRESSURE_HEAD_M:.0f} m in the current live state.",
                100.0 - 4.0 * len(low_nodes),
                affected_nodes=low_nodes,
                affected_pipes=aged_pipes[:8],
                risks=["Higher pressure can increase leak and burst exposure on aged pipes."],
            )
        )

    if severe_headloss or warning_headloss:
        targets = severe_headloss or warning_headloss
        rows.append(
            _recommendation_row(
                "L2",
                "dispatch_inspection",
                ", ".join(targets[:4]),
                "Inspect high-gradient pipe segments for leak, roughness, partial closure, or bottleneck.",
                f"Prioritizes {len(targets)} pipe segments with elevated head-loss gradient.",
                92.0 - 1.5 * len(targets),
                affected_nodes=low_nodes + marginal_nodes,
                affected_pipes=targets[:12],
                risks=["Inspection improves diagnosis but does not immediately recover service pressure."],
            )
        )

    if high_nodes and aged_pipes:
        rows.append(
            _recommendation_row(
                "L3",
                "decrease_pump_speed",
                "source",
                "Reduce source head in small steps while watching marginal demand nodes.",
                f"Relieves {len(high_nodes)} high-pressure nodes and aged-pipe stress exposure.",
                84.0 - 3.0 * len(low_nodes),
                affected_nodes=high_nodes + marginal_nodes,
                affected_pipes=aged_pipes[:12],
                risks=["Can create low-pressure service violations at remote demand nodes."],
            )
        )

    if not rows:
        rows.append(
            _recommendation_row(
                "L0",
                "no_action",
                "",
                "Keep the current live control settings.",
                "The current live snapshot satisfies minimum pressure without detected severe head-loss stress.",
                100.0,
                affected_nodes=[],
                affected_pipes=[],
                risks=["Continue monitoring live demand, pressure, leak, and aging indicators."],
            )
        )
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def _recommendation_row(
    action_id: str,
    action_type: str,
    target_id: str,
    description: str,
    expected_effect: str,
    score: float,
    affected_nodes: list[str],
    affected_pipes: list[str],
    risks: list[str],
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "action_type": action_type,
        "target_id": target_id,
        "description": description,
        "expected_effect": expected_effect,
        "score": round(float(score), 3),
        "affected_nodes": ", ".join(affected_nodes[:12]),
        "affected_pipes": ", ".join(affected_pipes[:12]),
        "risks": " ".join(risks),
    }


def live_state_cache_key(state: LiveScenarioState) -> tuple[Any, ...]:
    return (
        pd.Timestamp(state.timestamp).isoformat(),
        round(float(state.global_demand_multiplier), 6),
        tuple(sorted((k, v.multiplier, v.extra_demand_lps) for k, v in state.demand_overrides.items())),
        state.pressure_mode,
        round(float(state.manual_source_head_m), 6),
        bool(state.include_minor_losses),
        bool(state.leak_enabled),
        state.leak_target_type,
        state.leak_target_id,
        round(float(state.leak_demand_lps), 6),
        tuple(
            sorted(
                (
                    pipe_id,
                    override.material,
                    override.install_year,
                    override.repair_count,
                    override.leak_history_count,
                    override.diameter_mm,
                    override.aging_score_override,
                )
                for pipe_id, override in state.pipe_overrides.items()
            )
        ),
    )


def _base_source_head(tables: Mapping[str, pd.DataFrame]) -> float:
    reservoirs = tables.get("reservoirs", pd.DataFrame())
    if reservoirs.empty:
        return 70.0
    return float(reservoirs.iloc[0]["head_m"])


def _demand_nodes(node_results: pd.DataFrame) -> pd.DataFrame:
    return node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")]


def _manual_summary(
    demand_nodes: pd.DataFrame,
    required_source_head_m: float,
    source_delta_m: float,
) -> dict[str, Any]:
    return {
        "required_source_head_m": round(float(required_source_head_m), 4),
        "source_head_delta_m": round(float(source_delta_m), 4),
        "required_pump_head_gain_m": round(max(float(source_delta_m), 0.0), 4),
        "min_pressure_head_m": round(float(demand_nodes["pressure_head_m"].min()), 4),
        "max_pressure_head_m": round(float(demand_nodes["pressure_head_m"].max()), 4),
        "pressure_violations": int((demand_nodes["pressure_head_m"] < MIN_PRESSURE_HEAD_M).sum()),
        "high_pressure_nodes": int((demand_nodes["pressure_head_m"] > HIGH_PRESSURE_STRESS_M).sum()),
        "within_hydraulic_bounds": bool(
            (demand_nodes["pressure_head_m"] >= MIN_PRESSURE_HEAD_M).all()
            and (demand_nodes["pressure_head_m"] <= HIGH_PRESSURE_STRESS_M).all()
        ),
        "feasible": True,
    }


def _pressure_status(pressure_head_m: float) -> str:
    value = float(pressure_head_m)
    if value < 10.0:
        return "critical"
    if value < 15.0:
        return "violation"
    if value < 20.0:
        return "marginal"
    if value < 60.0:
        return "normal"
    return "high-pressure stress"
