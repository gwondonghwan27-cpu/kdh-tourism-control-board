"""Dynamic demand simulation and minimum source-head search."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from aging_water_network.config import HIGH_PRESSURE_STRESS_M, MIN_PRESSURE_HEAD_M
from aging_water_network.data.loaders import ensure_mock_data
from aging_water_network.hydraulics.simulator import run_hydraulic_simulation


def aggregate_household_demands(
    tables: Mapping[str, pd.DataFrame],
    timestamps: Iterable[str | pd.Timestamp] | None = None,
) -> pd.DataFrame:
    """Aggregate household AMI demand readings into node-level demand by timestamp."""

    households = tables.get("households", pd.DataFrame())
    demand_ts = tables.get("household_demand_timeseries", pd.DataFrame())
    if households.empty or demand_ts.empty:
        return pd.DataFrame(columns=["timestamp", "node_id", "demand_lps"])

    frame = demand_ts.merge(
        households[["household_id", "node_id", "dma_id"]],
        on="household_id",
        how="left",
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["demand_lps"] = pd.to_numeric(frame["demand_lps"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["timestamp", "node_id"])

    if timestamps is not None:
        selected = {pd.Timestamp(value) for value in timestamps}
        frame = frame[frame["timestamp"].isin(selected)]

    return (
        frame.groupby(["timestamp", "node_id"], as_index=False)["demand_lps"]
        .sum()
        .sort_values(["timestamp", "node_id"])
        .reset_index(drop=True)
    )


def build_time_step_tables(
    tables: Mapping[str, pd.DataFrame],
    node_demands: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Return copied tables whose node demand reflects one time step."""

    copied = {name: frame.copy() for name, frame in tables.items()}
    demand_lookup = node_demands.set_index("node_id")["demand_lps"].to_dict()
    nodes = copied["nodes"].copy()
    is_junction = nodes["node_type"].astype(str).str.lower().eq("junction")
    nodes.loc[is_junction, "base_demand_lps"] = (
        nodes.loc[is_junction, "node_id"].astype(str).map(demand_lookup).fillna(0.0)
    )
    nodes.loc[~is_junction, "base_demand_lps"] = 0.0
    copied["nodes"] = nodes
    return copied


def apply_leak_demand(
    tables: Mapping[str, pd.DataFrame],
    target_type: str,
    target_id: str,
    leak_demand_lps: float,
) -> tuple[dict[str, pd.DataFrame], dict[str, str | float]]:
    """Inject leak demand at a selected node or at the downstream end of a pipe."""

    copied = {name: frame.copy() for name, frame in tables.items()}
    leak_amount = max(float(leak_demand_lps), 0.0)
    target_kind = str(target_type).lower()
    leak_node_id = str(target_id)
    leak_pipe_id = ""

    if target_kind == "pipe":
        pipes = copied["pipes"]
        match = pipes[pipes["pipe_id"].astype(str).eq(str(target_id))]
        if match.empty:
            raise ValueError(f"Unknown leak pipe: {target_id}")
        pipe = match.iloc[0]
        leak_pipe_id = str(pipe["pipe_id"])
        leak_node_id = str(pipe["to_node"])
    elif target_kind == "node":
        if str(target_id) not in set(copied["nodes"]["node_id"].astype(str)):
            raise ValueError(f"Unknown leak node: {target_id}")
    else:
        raise ValueError("target_type must be 'node' or 'pipe'")

    nodes = copied["nodes"].copy()
    mask = nodes["node_id"].astype(str).eq(leak_node_id)
    nodes.loc[mask, "base_demand_lps"] = (
        pd.to_numeric(nodes.loc[mask, "base_demand_lps"], errors="coerce").fillna(0.0)
        + leak_amount
    )
    copied["nodes"] = nodes
    return copied, {
        "leak_node_id": leak_node_id,
        "leak_pipe_id": leak_pipe_id,
        "leak_demand_lps": leak_amount,
    }


def rank_leak_candidates(
    baseline_node_results: pd.DataFrame,
    leak_node_results: pd.DataFrame,
    pipes: pd.DataFrame,
    aging_scores: pd.DataFrame | None = None,
    top_n: int = 8,
) -> pd.DataFrame:
    """Rank pipes by pressure-drop signature and optional aging score."""

    if baseline_node_results.empty or leak_node_results.empty or pipes.empty:
        return pd.DataFrame(
            columns=[
                "pipe_id",
                "from_node",
                "to_node",
                "mean_pressure_drop_m",
                "aging_score",
                "leak_suspect_score",
            ]
        )

    pressure = baseline_node_results[["node_id", "pressure_head_m"]].merge(
        leak_node_results[["node_id", "pressure_head_m"]],
        on="node_id",
        how="inner",
        suffixes=("_baseline", "_observed"),
    )
    pressure["pressure_drop_m"] = (
        pressure["pressure_head_m_baseline"] - pressure["pressure_head_m_observed"]
    ).clip(lower=0.0)
    drop_lookup = pressure.set_index("node_id")["pressure_drop_m"].to_dict()

    aging_lookup: dict[str, float] = {}
    if aging_scores is not None and not aging_scores.empty and {"pipe_id", "aging_score"}.issubset(
        aging_scores.columns
    ):
        aging_lookup = dict(
            zip(aging_scores["pipe_id"].astype(str), pd.to_numeric(aging_scores["aging_score"], errors="coerce").fillna(0.0))
        )

    rows: list[dict[str, object]] = []
    for pipe in pipes.to_dict("records"):
        from_node = str(pipe["from_node"])
        to_node = str(pipe["to_node"])
        drop = (float(drop_lookup.get(from_node, 0.0)) + float(drop_lookup.get(to_node, 0.0))) / 2.0
        rows.append(
            {
                "pipe_id": str(pipe["pipe_id"]),
                "from_node": from_node,
                "to_node": to_node,
                "mean_pressure_drop_m": drop,
                "aging_score": float(aging_lookup.get(str(pipe["pipe_id"]), 0.0)),
            }
        )

    result = pd.DataFrame(rows)
    max_drop = float(result["mean_pressure_drop_m"].max() or 0.0)
    result["drop_score"] = result["mean_pressure_drop_m"] / max_drop if max_drop > 0 else 0.0
    result["leak_suspect_score"] = (0.78 * result["drop_score"] + 0.22 * result["aging_score"]).round(4)
    return (
        result.sort_values(["leak_suspect_score", "mean_pressure_drop_m"], ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def find_minimum_source_head(
    tables: Mapping[str, pd.DataFrame],
    min_pressure_head_m: float = MIN_PRESSURE_HEAD_M,
    max_pressure_head_m: float = HIGH_PRESSURE_STRESS_M,
    source_head_bounds_m: tuple[float, float] = (35.0, 110.0),
    tolerance_m: float = 0.05,
    include_minor_losses: bool = False,
) -> dict[str, object]:
    """Find the lowest source head that keeps all demand nodes above the threshold."""

    reservoirs = tables.get("reservoirs", pd.DataFrame())
    base_source_head = float(reservoirs.iloc[0]["head_m"]) if not reservoirs.empty else 70.0
    low, high = source_head_bounds_m

    def simulate_at(source_head: float) -> dict[str, object]:
        return run_hydraulic_simulation(
            tables=tables,
            min_pressure_head_m=min_pressure_head_m,
            source_head_delta_m=source_head - base_source_head,
            include_minor_losses=include_minor_losses,
            prefer_wntr=False,
        )

    base_result = simulate_at(base_source_head)
    base_nodes = _demand_nodes(base_result["node_results"])
    if base_nodes.empty:
        return _summary_from_result(
            base_result,
            source_head_m=base_source_head,
            base_source_head_m=base_source_head,
            feasible=False,
            min_pressure_head_m=min_pressure_head_m,
            max_pressure_head_m=max_pressure_head_m,
        )

    base_min_pressure = float(base_nodes["pressure_head_m"].min())
    required_source_head = base_source_head + (min_pressure_head_m - base_min_pressure)
    required_source_head = min(max(required_source_head + tolerance_m, low), high)
    best_result = simulate_at(required_source_head)
    best_nodes = _demand_nodes(best_result["node_results"])
    feasible = float(best_nodes["pressure_head_m"].min()) >= min_pressure_head_m
    return _summary_from_result(
        best_result,
        source_head_m=required_source_head,
        base_source_head_m=base_source_head,
        feasible=feasible,
        min_pressure_head_m=min_pressure_head_m,
        max_pressure_head_m=max_pressure_head_m,
    )


def run_dynamic_demand_simulation(
    data_dir: str | Path = "data/mock",
    tables: Mapping[str, pd.DataFrame] | None = None,
    timestamps: Iterable[str | pd.Timestamp] | None = None,
    min_pressure_head_m: float = MIN_PRESSURE_HEAD_M,
    max_pressure_head_m: float = HIGH_PRESSURE_STRESS_M,
    source_head_bounds_m: tuple[float, float] = (35.0, 110.0),
    include_minor_losses: bool = False,
) -> dict[str, pd.DataFrame | dict[str, object]]:
    """Run a time-series simulation from household demand readings."""

    loaded = {name: frame.copy() for name, frame in tables.items()} if tables is not None else ensure_mock_data(data_dir)
    node_demand_ts = aggregate_household_demands(loaded, timestamps=timestamps)
    if node_demand_ts.empty:
        raise ValueError("No household demand time series is available for dynamic simulation.")

    summaries: list[dict[str, object]] = []
    node_frames: list[pd.DataFrame] = []
    pipe_frames: list[pd.DataFrame] = []
    for timestamp, node_demands in node_demand_ts.groupby("timestamp", sort=True):
        step_tables = build_time_step_tables(loaded, node_demands)
        search = find_minimum_source_head(
            step_tables,
            min_pressure_head_m=min_pressure_head_m,
            max_pressure_head_m=max_pressure_head_m,
            source_head_bounds_m=source_head_bounds_m,
            include_minor_losses=include_minor_losses,
        )
        result = search["result"]
        assert isinstance(result, dict)
        node_results = result["node_results"].copy()
        pipe_results = result["pipe_results"].copy()
        total_demand = float(node_demands["demand_lps"].sum())

        summary = dict(search["summary"])
        summary["timestamp"] = timestamp
        summary["total_demand_lps"] = round(total_demand, 5)
        summary["total_demand_m3h"] = round(total_demand * 3.6, 5)
        summaries.append(summary)

        node_results.insert(0, "timestamp", timestamp)
        pipe_results.insert(0, "timestamp", timestamp)
        node_frames.append(node_results)
        pipe_frames.append(pipe_results)

    summary_df = pd.DataFrame(summaries).sort_values("timestamp").reset_index(drop=True)
    return {
        "dynamic_summary": summary_df,
        "node_time_results": pd.concat(node_frames, ignore_index=True),
        "pipe_time_results": pd.concat(pipe_frames, ignore_index=True),
        "node_demand_timeseries": node_demand_ts,
        "metadata": {
            "min_pressure_head_m": float(min_pressure_head_m),
            "max_pressure_head_m": float(max_pressure_head_m),
            "include_minor_losses": bool(include_minor_losses),
            "time_steps": int(summary_df.shape[0]),
        },
    }


def _demand_nodes(node_results: pd.DataFrame) -> pd.DataFrame:
    return node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")]


def _summary_from_result(
    result: Mapping[str, object],
    source_head_m: float,
    base_source_head_m: float,
    feasible: bool,
    min_pressure_head_m: float,
    max_pressure_head_m: float,
) -> dict[str, object]:
    node_results = result["node_results"]
    assert isinstance(node_results, pd.DataFrame)
    demand_nodes = _demand_nodes(node_results)
    min_pressure = float(demand_nodes["pressure_head_m"].min())
    max_pressure = float(demand_nodes["pressure_head_m"].max())
    violations = int((demand_nodes["pressure_head_m"] < min_pressure_head_m).sum())
    high_pressure_nodes = int((demand_nodes["pressure_head_m"] > max_pressure_head_m).sum())
    pump_head_delta = source_head_m - base_source_head_m
    return {
        "summary": {
            "required_source_head_m": round(float(source_head_m), 4),
            "source_head_delta_m": round(float(pump_head_delta), 4),
            "required_pump_head_gain_m": round(max(float(pump_head_delta), 0.0), 4),
            "min_pressure_head_m": round(min_pressure, 4),
            "max_pressure_head_m": round(max_pressure, 4),
            "pressure_violations": violations,
            "high_pressure_nodes": high_pressure_nodes,
            "within_hydraulic_bounds": bool(feasible and violations == 0 and high_pressure_nodes == 0),
            "feasible": bool(feasible),
        },
        "result": result,
    }
