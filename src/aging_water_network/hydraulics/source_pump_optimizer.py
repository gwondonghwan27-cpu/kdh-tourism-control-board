"""Source and pump operating predictions for low-pressure recovery."""

from __future__ import annotations

import copy
import heapq
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from aging_water_network.config import MIN_PRESSURE_HEAD_M
from aging_water_network.hydraulics.simulator import compute_fallback_aging_scores, compute_pipe_hydraulic_params, run_hydraulic_simulation


_RESULT_CACHE: dict[str, dict[str, Any]] = {}
_WARM_STARTS: dict[str, dict[str, float]] = {}
_MAX_SENSITIVITY_CANDIDATES = 8
_MAX_ACTIVE_SET_ROUNDS = 4
_CRITICAL_TOP_FRACTION = 0.10
_CRITICAL_DMA_TOP_N = 3


def clear_source_pump_optimizer_cache() -> None:
    """Clear in-memory optimization cache and warm-starts.

    This is primarily useful for tests and for long-running dashboard sessions
    after a model reload.
    """

    _RESULT_CACHE.clear()
    _WARM_STARTS.clear()


def predict_source_pump_operation(
    tables: Mapping[str, pd.DataFrame],
    *,
    min_pressure_head_m: float = MIN_PRESSURE_HEAD_M,
    demand_multiplier: float = 1.0,
    max_boost_m: float = 150.0,
    tolerance_m: float = 0.05,
) -> dict[str, Any]:
    """Predict low-cost Source/Pump operating changes that remove low pressure.

    The optimizer is intentionally lightweight for dashboard use:
    exact-result cache -> warm-start -> sensitivity screening -> constrained
    scalar search over the best controls -> EPANET-formula verification.
    """

    base_tables = {name: frame.copy() for name, frame in tables.items()}
    cache_key = _cache_key(base_tables, min_pressure_head_m, demand_multiplier, max_boost_m)
    if cache_key in _RESULT_CACHE:
        cached = copy.deepcopy(_RESULT_CACHE[cache_key])
        cached["cache_hit"] = True
        return cached

    topology_key = _topology_key(base_tables, min_pressure_head_m)
    simulation_count = 0

    def simulate(tables_for_run: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
        nonlocal simulation_count
        simulation_count += 1
        return _simulate(tables_for_run, min_pressure_head_m, demand_multiplier)

    baseline = simulate(base_tables)
    baseline_min = _minimum_demand_pressure(baseline["node_results"])
    baseline_low_nodes = _low_pressure_nodes(baseline["node_results"], min_pressure_head_m)
    controls = _controllable_assets(base_tables, baseline["pipe_results"])
    critical_group = _critical_junction_group(base_tables, baseline, min_pressure_head_m)
    target_nodes = _initial_target_nodes(baseline_low_nodes, critical_group["nodes"])
    warm_start = _WARM_STARTS.get(topology_key, {})
    warm_started = False

    if not baseline_low_nodes:
        selected_boost = 0.0
        optimized = baseline
        feasible = True
        selected_boosts = {control["key"]: 0.0 for control in controls}
        sensitivity_rows: list[dict[str, Any]] = []
        active_nodes = target_nodes
        active_set_rounds = 0
    else:
        sensitivity_rows = _sensitivity_screen(
            base_tables,
            controls,
            baseline["node_results"],
            target_nodes,
            min_pressure_head_m,
            demand_multiplier,
            simulate,
        )
        candidates = _candidate_controls(controls, sensitivity_rows)
        if not candidates:
            candidates = controls

        warm_result = None
        if warm_start:
            warm_boosts = {control["key"]: min(float(warm_start.get(control["key"], 0.0)), max_boost_m) for control in controls}
            if any(value > 0 for value in warm_boosts.values()):
                warm_result = simulate(_apply_control_boosts(base_tables, warm_boosts))
                warm_started = True

        optimized, selected_boosts, feasible, active_nodes, active_set_rounds = _constrained_search(
            base_tables,
            candidates,
            sensitivity_rows,
            min_pressure_head_m,
            demand_multiplier,
            max_boost_m,
            tolerance_m,
            target_nodes,
            simulate,
            warm_result=warm_result,
            warm_boosts=warm_start,
        )
        selected_boost = max(selected_boosts.values(), default=0.0)

    optimized_low_nodes = _low_pressure_nodes(optimized["node_results"], min_pressure_head_m)
    boosted_tables = _apply_control_boosts(base_tables, selected_boosts)
    control_plan_rows = _control_plan(controls, selected_boosts, optimized["pipe_results"])
    source_rows = _source_summaries(base_tables, boosted_tables, optimized["pipe_results"], control_plan_rows)
    pump_rows = _pump_summaries(base_tables, boosted_tables, optimized["pipe_results"], control_plan_rows)
    result = {
        "target_min_pressure_m": round(float(min_pressure_head_m), 4),
        "recommended_boost_m": round(float(selected_boost), 4),
        "feasible": bool(feasible and not optimized_low_nodes),
        "baseline_min_pressure_m": round(float(baseline_min), 4),
        "predicted_min_pressure_m": round(float(_minimum_demand_pressure(optimized["node_results"])), 4),
        "low_pressure_nodes_before": baseline_low_nodes,
        "low_pressure_nodes_after": optimized_low_nodes,
        "sources": source_rows,
        "pumps": pump_rows,
        "total_source_outflow_lps": round(sum(item["predicted_outflow_lps"] for item in source_rows), 4),
        "total_pump_flow_lps": round(sum(abs(item["predicted_flow_lps"]) for item in pump_rows), 4),
        "optimization_method": "cache_warm_start_sdi_active_set_sensitivity_constrained_validation",
        "cache_hit": False,
        "warm_start_used": warm_started,
        "epanet_validation_passed": bool(not optimized_low_nodes),
        "hydraulic_simulation_count": simulation_count,
        "critical_junction_count": len(active_nodes),
        "critical_junctions": critical_group["rows"][:12],
        "active_set_rounds": active_set_rounds,
        "sensitivity_candidates": sensitivity_rows[:_MAX_SENSITIVITY_CANDIDATES],
        "control_plan": control_plan_rows,
    }
    _RESULT_CACHE[cache_key] = copy.deepcopy(result)
    if result["feasible"]:
        _WARM_STARTS[topology_key] = dict(selected_boosts)
    return result


def _simulate(
    tables: Mapping[str, pd.DataFrame],
    min_pressure_head_m: float,
    demand_multiplier: float,
) -> dict[str, Any]:
    return run_hydraulic_simulation(
        tables=tables,
        min_pressure_head_m=min_pressure_head_m,
        demand_multiplier=demand_multiplier,
        prefer_wntr=False,
    )


def _boost_source_pump_tables(tables: Mapping[str, pd.DataFrame], boost_m: float) -> dict[str, pd.DataFrame]:
    controls = _controllable_assets(tables)
    return _apply_control_boosts(tables, {control["key"]: float(boost_m) for control in controls})


def _controllable_assets(tables: Mapping[str, pd.DataFrame], pipe_results: pd.DataFrame | None = None) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    pumps = tables.get("pumps", pd.DataFrame())
    if isinstance(pumps, pd.DataFrame) and not pumps.empty:
        statuses = pumps.get("status", pd.Series("on", index=pumps.index)).astype(str).str.lower()
        for index, pump in pumps[statuses.ne("off")].iterrows():
            pump_id = str(pump.get("pump_id", f"PUMP_{index}"))
            controls.append(
                {
                    "key": f"pump:{pump_id}",
                    "type": "pump",
                    "id": pump_id,
                    "index": index,
                    "from_node": str(pump.get("from_node", "")),
                    "to_node": str(pump.get("to_node", "")),
                    "cost_weight": 1.0,
                }
            )
    reservoirs = tables.get("reservoirs", pd.DataFrame())
    if isinstance(reservoirs, pd.DataFrame) and not reservoirs.empty:
        for index, reservoir in reservoirs.iterrows():
            source_id = str(reservoir.get("reservoir_id") or reservoir.get("node_id") or f"SOURCE_{index}")
            node_id = str(reservoir.get("node_id", ""))
            baseline_outflow = _node_outflow_lps(node_id, pipe_results) if pipe_results is not None else 0.0
            controls.append(
                {
                    "key": f"source:{source_id}",
                    "type": "source",
                    "id": source_id,
                    "index": index,
                    "node_id": node_id,
                    "baseline_outflow_lps": round(float(baseline_outflow), 4),
                    "cost_weight": 1.25 if baseline_outflow > 0.05 else 4.0,
                }
            )
    return controls


def _apply_control_boosts(tables: Mapping[str, pd.DataFrame], boosts: Mapping[str, float]) -> dict[str, pd.DataFrame]:
    boosted = {name: frame.copy() for name, frame in tables.items()}
    controls = _controllable_assets(boosted)
    for control in controls:
        boost = float(boosts.get(control["key"], 0.0) or 0.0)
        if boost == 0:
            continue
        if control["type"] == "pump" and "pumps" in boosted and not boosted["pumps"].empty:
            index = control["index"]
            boosted["pumps"]["base_head_gain_m"] = pd.to_numeric(boosted["pumps"].get("base_head_gain_m", 0.0), errors="coerce").fillna(0.0).astype(float)
            boosted["pumps"]["speed_multiplier"] = pd.to_numeric(boosted["pumps"].get("speed_multiplier", 1.0), errors="coerce").fillna(1.0).astype(float)
            boosted["pumps"].loc[index, "base_head_gain_m"] = float(boosted["pumps"].loc[index].get("base_head_gain_m", 0.0) or 0.0) + boost
            boosted["pumps"].loc[index, "speed_multiplier"] = 1.0
        if control["type"] == "source" and "reservoirs" in boosted and not boosted["reservoirs"].empty:
            index = control["index"]
            boosted["reservoirs"]["head_m"] = pd.to_numeric(boosted["reservoirs"].get("head_m", 0.0), errors="coerce").fillna(0.0).astype(float)
            boosted["reservoirs"].loc[index, "head_m"] = float(boosted["reservoirs"].loc[index].get("head_m", 0.0) or 0.0) + boost
    return boosted


def _sensitivity_screen(
    tables: Mapping[str, pd.DataFrame],
    controls: list[dict[str, Any]],
    baseline_nodes: pd.DataFrame,
    target_node_ids: list[str],
    min_pressure_head_m: float,
    demand_multiplier: float,
    simulate: Any = None,
    step_m: float = 1.0,
) -> list[dict[str, Any]]:
    simulate = simulate or (lambda run_tables: _simulate(run_tables, min_pressure_head_m, demand_multiplier))
    baseline_deficit = _pressure_deficit(baseline_nodes, target_node_ids, min_pressure_head_m)
    baseline_min = _minimum_demand_pressure(baseline_nodes)
    rows: list[dict[str, Any]] = []
    for control in controls:
        simulated = simulate(_apply_control_boosts(tables, {control["key"]: step_m}))
        deficit = _pressure_deficit(simulated["node_results"], target_node_ids, min_pressure_head_m)
        min_pressure = _minimum_demand_pressure(simulated["node_results"])
        improvement = max(baseline_deficit - deficit, 0.0)
        min_gain = max(min_pressure - baseline_min, 0.0) if pd.notna(min_pressure) and pd.notna(baseline_min) else 0.0
        score = (improvement + min_gain * 0.35) / max(float(control.get("cost_weight", 1.0)) * step_m, 1e-9)
        rows.append(
            {
                "control_key": control["key"],
                "asset_type": control["type"],
                "asset_id": control["id"],
                "score": round(float(score), 6),
                "deficit_reduction_m": round(float(improvement), 6),
                "min_pressure_gain_m": round(float(min_gain), 6),
            }
        )
    return sorted(rows, key=lambda item: item["score"], reverse=True)


def _candidate_controls(controls: list[dict[str, Any]], sensitivity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positive_keys = [row["control_key"] for row in sensitivity_rows if float(row.get("score", 0.0)) > 0]
    selected_keys = set(positive_keys[:_MAX_SENSITIVITY_CANDIDATES])
    return [control for control in controls if control["key"] in selected_keys]


def _constrained_search(
    tables: Mapping[str, pd.DataFrame],
    candidates: list[dict[str, Any]],
    sensitivity_rows: list[dict[str, Any]],
    min_pressure_head_m: float,
    demand_multiplier: float,
    max_boost_m: float,
    tolerance_m: float,
    target_node_ids: list[str],
    simulate: Any = None,
    *,
    warm_result: dict[str, Any] | None = None,
    warm_boosts: Mapping[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, float], bool, list[str], int]:
    simulate = simulate or (lambda run_tables: _simulate(run_tables, min_pressure_head_m, demand_multiplier))
    weights = _candidate_weights(candidates, sensitivity_rows)
    active_nodes = list(dict.fromkeys(map(str, target_node_ids)))
    optimized: dict[str, Any] | None = warm_result
    selected: dict[str, float] = {control["key"]: float((warm_boosts or {}).get(control["key"], 0.0) or 0.0) for control in candidates}
    rounds = 0

    for round_index in range(_MAX_ACTIVE_SET_ROUNDS):
        rounds = round_index + 1
        optimized, selected, target_feasible = _single_target_search(
            tables,
            candidates,
            weights,
            min_pressure_head_m,
            max_boost_m,
            tolerance_m,
            active_nodes,
            simulate,
            warm_result=optimized if round_index == 0 else None,
            warm_boosts=selected,
        )
        if not target_feasible:
            return optimized, selected, False, active_nodes, rounds

        full_low_nodes = _low_pressure_nodes(optimized["node_results"], min_pressure_head_m)
        if not full_low_nodes:
            return optimized, selected, True, active_nodes, rounds

        before = len(active_nodes)
        active_nodes = list(dict.fromkeys([*active_nodes, *[item["node_id"] for item in full_low_nodes]]))
        if len(active_nodes) == before:
            break

    final_low_nodes = _low_pressure_nodes(optimized["node_results"], min_pressure_head_m) if optimized is not None else []
    return optimized or simulate(_apply_control_boosts(tables, selected)), selected, not final_low_nodes, active_nodes, rounds


def _single_target_search(
    tables: Mapping[str, pd.DataFrame],
    candidates: list[dict[str, Any]],
    weights: Mapping[str, float],
    min_pressure_head_m: float,
    max_boost_m: float,
    tolerance_m: float,
    target_node_ids: list[str],
    simulate: Any,
    *,
    warm_result: dict[str, Any] | None = None,
    warm_boosts: Mapping[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, float], bool]:
    zero_boosts = {control["key"]: 0.0 for control in candidates}
    warm_candidate_boosts = {control["key"]: float((warm_boosts or {}).get(control["key"], 0.0) or 0.0) for control in candidates}
    if warm_result is not None and _minimum_target_pressure(warm_result["node_results"], target_node_ids) >= min_pressure_head_m:
        high = max(warm_candidate_boosts.values(), default=0.0)
        best_result = warm_result
        best_boosts = warm_candidate_boosts
    else:
        high = min(max(1.0, tolerance_m), float(max_boost_m))
        best_result = None
        best_boosts = zero_boosts
        while high <= float(max_boost_m):
            candidate_boosts = {control["key"]: high * weights.get(control["key"], 0.0) for control in candidates}
            candidate = simulate(_apply_control_boosts(tables, candidate_boosts))
            if _minimum_target_pressure(candidate["node_results"], target_node_ids) >= min_pressure_head_m:
                best_result = candidate
                best_boosts = candidate_boosts
                break
            high *= 2.0

        if best_result is None:
            best_boosts = {control["key"]: float(max_boost_m) for control in candidates}
            best_result = simulate(_apply_control_boosts(tables, best_boosts))
            if _minimum_target_pressure(best_result["node_results"], target_node_ids) < min_pressure_head_m:
                return best_result, best_boosts, False
            high = float(max_boost_m)

    low = 0.0
    optimized = best_result
    selected = best_boosts
    while high - low > tolerance_m:
        mid = (low + high) / 2.0
        candidate_boosts = {control["key"]: mid * weights.get(control["key"], 0.0) for control in candidates}
        candidate = simulate(_apply_control_boosts(tables, candidate_boosts))
        if _minimum_target_pressure(candidate["node_results"], target_node_ids) >= min_pressure_head_m:
            high = mid
            optimized = candidate
            selected = candidate_boosts
        else:
            low = mid
    return optimized, selected, True


def _candidate_weights(candidates: list[dict[str, Any]], sensitivity_rows: list[dict[str, Any]]) -> dict[str, float]:
    scores = {row["control_key"]: max(float(row.get("score", 0.0)), 0.0) for row in sensitivity_rows}
    max_score = max([scores.get(control["key"], 0.0) for control in candidates] + [0.0])
    if max_score <= 0:
        return {control["key"]: 1.0 for control in candidates}
    return {control["key"]: max(scores.get(control["key"], 0.0) / max_score, 0.15) for control in candidates}


def _critical_junction_group(
    tables: Mapping[str, pd.DataFrame],
    baseline: Mapping[str, Any],
    min_pressure_head_m: float,
) -> dict[str, Any]:
    node_results = baseline.get("node_results", pd.DataFrame())
    if not isinstance(node_results, pd.DataFrame) or node_results.empty:
        return {"nodes": [], "rows": []}

    demand_nodes = node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")].copy()
    if demand_nodes.empty:
        return {"nodes": [], "rows": []}

    distances = _multi_source_sdi(tables)
    graph_degree = _node_degrees(tables)
    demand_nodes["node_id"] = demand_nodes["node_id"].astype(str)
    demand_nodes["sdi_raw"] = demand_nodes["node_id"].map(distances).replace([math.inf, -math.inf], pd.NA)
    demand_nodes["sdi_score"] = _normalize_series(demand_nodes["sdi_raw"])
    demand_nodes["elevation_score"] = _normalize_series(pd.to_numeric(demand_nodes.get("elevation_m", 0.0), errors="coerce"))
    demand_nodes["demand_score"] = _normalize_series(pd.to_numeric(demand_nodes.get("base_demand_lps", 0.0), errors="coerce"))
    pressure = pd.to_numeric(demand_nodes["pressure_head_m"], errors="coerce")
    demand_nodes["low_pressure_score"] = ((float(min_pressure_head_m) - pressure).clip(lower=0) / max(float(min_pressure_head_m), 1.0)).fillna(0.0)
    demand_nodes["terminal_score"] = demand_nodes["node_id"].map(lambda node_id: 1.0 if graph_degree.get(str(node_id), 0) <= 1 else 0.0)
    demand_nodes["risk_score"] = (
        0.46 * demand_nodes["sdi_score"]
        + 0.16 * demand_nodes["elevation_score"]
        + 0.14 * demand_nodes["demand_score"]
        + 0.19 * demand_nodes["low_pressure_score"]
        + 0.05 * demand_nodes["terminal_score"]
    )

    selected: set[str] = set()
    top_n = max(1, math.ceil(len(demand_nodes) * _CRITICAL_TOP_FRACTION))
    selected.update(demand_nodes.sort_values("risk_score", ascending=False).head(top_n)["node_id"].astype(str))
    selected.update(demand_nodes[demand_nodes["low_pressure_score"] > 0]["node_id"].astype(str))
    selected.update(demand_nodes[demand_nodes["terminal_score"] > 0].sort_values("risk_score", ascending=False).head(max(3, top_n))["node_id"].astype(str))
    selected.update(demand_nodes.sort_values("elevation_score", ascending=False).head(max(2, top_n))["node_id"].astype(str))
    selected.update(demand_nodes.sort_values("demand_score", ascending=False).head(max(2, top_n))["node_id"].astype(str))
    if "dma" in demand_nodes.columns:
        for _, group in demand_nodes.groupby(demand_nodes["dma"].astype(str)):
            selected.update(group.sort_values("risk_score", ascending=False).head(_CRITICAL_DMA_TOP_N)["node_id"].astype(str))

    rows = []
    for row in demand_nodes.sort_values("risk_score", ascending=False).to_dict("records"):
        node_id = str(row.get("node_id", ""))
        if node_id not in selected:
            continue
        rows.append(
            {
                "node_id": node_id,
                "risk_score": round(float(row.get("risk_score", 0.0) or 0.0), 4),
                "sdi_score": round(float(row.get("sdi_score", 0.0) or 0.0), 4),
                "elevation_score": round(float(row.get("elevation_score", 0.0) or 0.0), 4),
                "demand_score": round(float(row.get("demand_score", 0.0) or 0.0), 4),
                "pressure_head_m": round(float(row.get("pressure_head_m", 0.0) or 0.0), 4),
                "reason": _critical_reason(row),
            }
        )
    return {"nodes": [item["node_id"] for item in rows], "rows": rows}


def _multi_source_sdi(tables: Mapping[str, pd.DataFrame]) -> dict[str, float]:
    graph = _sdi_graph(tables)
    sources = _supply_nodes(tables)
    if not graph or not sources:
        return {}

    distances = {node_id: math.inf for node_id in graph}
    queue: list[tuple[float, str]] = []
    for source in sources:
        if source not in graph:
            continue
        distances[source] = 0.0
        heapq.heappush(queue, (0.0, source))

    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance > distances.get(node_id, math.inf):
            continue
        for neighbor, weight in graph.get(node_id, []):
            next_distance = distance + weight
            if next_distance < distances.get(neighbor, math.inf):
                distances[neighbor] = next_distance
                heapq.heappush(queue, (next_distance, neighbor))
    return distances


def _sdi_graph(tables: Mapping[str, pd.DataFrame]) -> dict[str, list[tuple[str, float]]]:
    pipes = tables.get("pipes", pd.DataFrame())
    if not isinstance(pipes, pd.DataFrame) or pipes.empty:
        return {}
    params = compute_pipe_hydraulic_params(pipes, compute_fallback_aging_scores(pipes))
    param_lookup = params.set_index("pipe_id").to_dict("index") if "pipe_id" in params.columns else {}
    valve_lookup = _valve_penalty_by_pipe(tables.get("valves", pd.DataFrame()))

    records: list[dict[str, Any]] = []
    for pipe in pipes.to_dict("records"):
        pipe_id = str(pipe.get("pipe_id", ""))
        param = param_lookup.get(pipe_id, {})
        length_m = max(float(pipe.get("length_m", 1.0) or 1.0), 1.0)
        diameter_m = max(float(pipe.get("diameter_mm", 100.0) or 100.0) / 1000.0, 0.025)
        roughness = max(float(param.get("adjusted_roughness_c", pipe.get("roughness_c", 100.0)) or 100.0), 1.0)
        raw_resistance = length_m / (roughness**1.852 * diameter_m**4.871)
        records.append(
            {
                "from_node": str(pipe.get("from_node", "")),
                "to_node": str(pipe.get("to_node", "")),
                "raw_resistance": raw_resistance,
                "aging_score": float(param.get("aging_score", 0.0) or 0.0),
                "leak_score": min(float(pipe.get("leak_history_count", 0.0) or 0.0) / 3.0, 1.0),
                "minor_loss_score": min(float(param.get("minor_loss_k", pipe.get("minor_loss_k", 0.0)) or 0.0) / 8.0, 1.0),
                "valve_score": min((float(pipe.get("valve_count", 0.0) or 0.0) / 4.0) + valve_lookup.get(pipe_id, 0.0), 1.0),
            }
        )

    resistance_scores = _normalize_values([item["raw_resistance"] for item in records])
    graph: dict[str, list[tuple[str, float]]] = {}
    for item, resistance_score in zip(records, resistance_scores, strict=False):
        weight = max(
            0.001,
            0.65 * resistance_score
            + 0.15 * item["aging_score"]
            + 0.08 * item["leak_score"]
            + 0.07 * item["minor_loss_score"]
            + 0.05 * item["valve_score"],
        )
        a = item["from_node"]
        b = item["to_node"]
        if not a or not b:
            continue
        graph.setdefault(a, []).append((b, weight))
        graph.setdefault(b, []).append((a, weight))

    for pump in tables.get("pumps", pd.DataFrame()).to_dict("records") if isinstance(tables.get("pumps", pd.DataFrame()), pd.DataFrame) else []:
        if str(pump.get("status", "on")).lower() == "off":
            continue
        a = str(pump.get("from_node", ""))
        b = str(pump.get("to_node", ""))
        if a and b:
            graph.setdefault(a, []).append((b, 0.001))
            graph.setdefault(b, []).append((a, 0.001))
    return graph


def _supply_nodes(tables: Mapping[str, pd.DataFrame]) -> set[str]:
    nodes: set[str] = set()
    reservoirs = tables.get("reservoirs", pd.DataFrame())
    if isinstance(reservoirs, pd.DataFrame) and not reservoirs.empty:
        nodes.update(reservoirs.get("node_id", pd.Series(dtype=str)).dropna().astype(str))
    tanks = tables.get("tanks", pd.DataFrame())
    if isinstance(tanks, pd.DataFrame) and not tanks.empty:
        nodes.update(tanks.get("node_id", pd.Series(dtype=str)).dropna().astype(str))
    pumps = tables.get("pumps", pd.DataFrame())
    if isinstance(pumps, pd.DataFrame) and not pumps.empty:
        active = pumps[pumps.get("status", pd.Series("on", index=pumps.index)).astype(str).str.lower().ne("off")]
        nodes.update(active.get("to_node", pd.Series(dtype=str)).dropna().astype(str))
    return nodes


def _node_degrees(tables: Mapping[str, pd.DataFrame]) -> dict[str, int]:
    degree: dict[str, int] = {}
    pipes = tables.get("pipes", pd.DataFrame())
    if isinstance(pipes, pd.DataFrame):
        for pipe in pipes.to_dict("records"):
            for node_id in (str(pipe.get("from_node", "")), str(pipe.get("to_node", ""))):
                if node_id:
                    degree[node_id] = degree.get(node_id, 0) + 1
    return degree


def _valve_penalty_by_pipe(valves: pd.DataFrame | None) -> dict[str, float]:
    if valves is None or valves.empty or "pipe_id" not in valves.columns:
        return {}
    penalties: dict[str, float] = {}
    for valve in valves.to_dict("records"):
        pipe_id = str(valve.get("pipe_id", ""))
        status = str(valve.get("status", "open")).lower()
        status_penalty = 1.0 if status == "closed" else 0.6 if status == "partially_open" else 0.0
        loss_penalty = min(float(valve.get("minor_loss_k", 0.0) or 0.0) / 8.0, 1.0)
        penalties[pipe_id] = max(penalties.get(pipe_id, 0.0), status_penalty, loss_penalty)
    return penalties


def _initial_target_nodes(low_nodes: list[dict[str, Any]], critical_nodes: list[str]) -> list[str]:
    return list(dict.fromkeys([*[str(item["node_id"]) for item in low_nodes], *map(str, critical_nodes)]))


def _minimum_target_pressure(node_results: pd.DataFrame, target_node_ids: list[str]) -> float:
    if node_results.empty:
        return float("nan")
    frame = node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")]
    if target_node_ids:
        target_set = set(map(str, target_node_ids))
        target_frame = frame[frame["node_id"].astype(str).isin(target_set)]
        if not target_frame.empty:
            frame = target_frame
    if frame.empty:
        return float("nan")
    return float(pd.to_numeric(frame["pressure_head_m"], errors="coerce").min())


def _normalize_series(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    finite = values.dropna()
    if finite.empty:
        return pd.Series(0.0, index=series.index)
    low = float(finite.min())
    high = float(finite.max())
    if high <= low:
        return pd.Series(0.0, index=series.index)
    return ((values.fillna(low) - low) / (high - low)).clip(0.0, 1.0)


def _normalize_values(values: list[float]) -> list[float]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return [0.0 for _ in values]
    low = min(finite)
    high = max(finite)
    if high <= low:
        return [0.0 for _ in values]
    return [min(max((float(value) - low) / (high - low), 0.0), 1.0) if math.isfinite(float(value)) else 0.0 for value in values]


def _critical_reason(row: Mapping[str, Any]) -> str:
    reasons = []
    if float(row.get("low_pressure_score", 0.0) or 0.0) > 0:
        reasons.append("low_pressure")
    if float(row.get("sdi_score", 0.0) or 0.0) >= 0.75:
        reasons.append("high_sdi")
    if float(row.get("elevation_score", 0.0) or 0.0) >= 0.75:
        reasons.append("high_elevation")
    if float(row.get("demand_score", 0.0) or 0.0) >= 0.75:
        reasons.append("high_demand")
    if float(row.get("terminal_score", 0.0) or 0.0) > 0:
        reasons.append("terminal")
    return ",".join(reasons) or "representative"


def _pressure_deficit(node_results: pd.DataFrame, target_node_ids: list[str], threshold_m: float) -> float:
    if node_results.empty:
        return 0.0
    frame = node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")]
    if target_node_ids:
        frame = frame[frame["node_id"].astype(str).isin(set(map(str, target_node_ids)))]
    pressure = pd.to_numeric(frame["pressure_head_m"], errors="coerce")
    return float((float(threshold_m) - pressure).clip(lower=0).sum())


def _control_plan(
    controls: list[dict[str, Any]],
    boosts: Mapping[str, float],
    pipe_results: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows = []
    for control in controls:
        boost = float(boosts.get(control["key"], 0.0) or 0.0)
        if boost <= 0:
            continue
        flow = _control_flow_lps(control, pipe_results)
        rows.append(
            {
                "control_key": control["key"],
                "asset_type": control["type"],
                "asset_id": control["id"],
                "recommended_boost_m": round(boost, 4),
                "predicted_flow_lps": round(float(flow), 4),
                "flow_contribution_percent": 0.0,
                "status": "active" if abs(flow) > 0.05 else "hydraulic_head_only",
            }
        )
    total_flow = sum(abs(item["predicted_flow_lps"]) for item in rows)
    if total_flow > 0:
        for item in rows:
            item["flow_contribution_percent"] = round(abs(item["predicted_flow_lps"]) / total_flow * 100, 2)
    return rows


def _control_flow_lps(control: Mapping[str, Any], pipe_results: pd.DataFrame) -> float:
    if control.get("type") == "source":
        return _node_outflow_lps(str(control.get("node_id", "")), pipe_results)
    if control.get("type") == "pump":
        return _pump_flow_lps(
            {
                "pump_id": control.get("id", ""),
                "from_node": control.get("from_node", ""),
                "to_node": control.get("to_node", ""),
            },
            pipe_results,
        )
    return 0.0


def _minimum_demand_pressure(node_results: pd.DataFrame) -> float:
    demand_nodes = node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")]
    if demand_nodes.empty:
        return float("nan")
    return float(pd.to_numeric(demand_nodes["pressure_head_m"], errors="coerce").min())


def _cache_key(
    tables: Mapping[str, pd.DataFrame],
    min_pressure_head_m: float,
    demand_multiplier: float,
    max_boost_m: float,
) -> str:
    payload = {
        "tables": _table_signature(tables),
        "min_pressure_head_m": round(float(min_pressure_head_m), 6),
        "demand_multiplier": round(float(demand_multiplier), 6),
        "max_boost_m": round(float(max_boost_m), 6),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _topology_key(tables: Mapping[str, pd.DataFrame], min_pressure_head_m: float) -> str:
    payload = {
        "nodes": _records_for_signature(tables.get("nodes", pd.DataFrame()), ["node_id", "node_type"]),
        "pipes": _records_for_signature(tables.get("pipes", pd.DataFrame()), ["pipe_id", "from_node", "to_node"]),
        "pumps": _records_for_signature(tables.get("pumps", pd.DataFrame()), ["pump_id", "from_node", "to_node", "status"]),
        "reservoirs": _records_for_signature(tables.get("reservoirs", pd.DataFrame()), ["reservoir_id", "node_id"]),
        "min_pressure_head_m": round(float(min_pressure_head_m), 6),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _table_signature(tables: Mapping[str, pd.DataFrame]) -> dict[str, list[dict[str, Any]]]:
    return {name: _records_for_signature(frame) for name, frame in sorted(tables.items())}


def _records_for_signature(frame: pd.DataFrame | None, columns: list[str] | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    selected = frame.copy()
    if columns is not None:
        for column in columns:
            if column not in selected.columns:
                selected[column] = ""
        selected = selected[columns]
    selected = selected.reindex(sorted(selected.columns), axis=1).fillna("").astype(str)
    return selected.sort_values(by=list(selected.columns), kind="mergesort").to_dict("records")


def _low_pressure_nodes(node_results: pd.DataFrame, threshold_m: float) -> list[dict[str, Any]]:
    demand_nodes = node_results[node_results["node_type"].astype(str).str.lower().ne("reservoir")]
    low = demand_nodes[pd.to_numeric(demand_nodes["pressure_head_m"], errors="coerce") < float(threshold_m)]
    return [
        {
            "node_id": str(row["node_id"]),
            "pressure_head_m": round(float(row["pressure_head_m"]), 4),
        }
        for row in low.sort_values("pressure_head_m").head(12).to_dict("records")
    ]


def _source_summaries(
    base_tables: Mapping[str, pd.DataFrame],
    boosted_tables: Mapping[str, pd.DataFrame],
    pipe_results: pd.DataFrame,
    control_plan: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    reservoirs = base_tables.get("reservoirs", pd.DataFrame())
    boosted_reservoirs = boosted_tables.get("reservoirs", pd.DataFrame())
    boosted_lookup = boosted_reservoirs.set_index("node_id").to_dict("index") if not boosted_reservoirs.empty else {}
    rows: list[dict[str, Any]] = []
    plan_lookup = {str(item["control_key"]): item for item in control_plan or []}
    for reservoir in reservoirs.to_dict("records"):
        node_id = str(reservoir.get("node_id", ""))
        source_id = str(reservoir.get("reservoir_id") or node_id)
        boosted = boosted_lookup.get(node_id, {})
        plan = plan_lookup.get(f"source:{source_id}", {})
        rows.append(
            {
                "source_id": source_id,
                "node_id": node_id,
                "current_head_m": round(float(reservoir.get("head_m", 0.0) or 0.0), 4),
                "recommended_head_m": round(float(boosted.get("head_m", reservoir.get("head_m", 0.0)) or 0.0), 4),
                "predicted_outflow_lps": round(_node_outflow_lps(node_id, pipe_results), 4),
                "recommended_boost_m": round(float(plan.get("recommended_boost_m", 0.0) or 0.0), 4),
                "flow_contribution_percent": round(float(plan.get("flow_contribution_percent", 0.0) or 0.0), 2),
                "optimization_status": str(plan.get("status", "not_selected")),
            }
        )
    return rows


def _pump_summaries(
    base_tables: Mapping[str, pd.DataFrame],
    boosted_tables: Mapping[str, pd.DataFrame],
    pipe_results: pd.DataFrame,
    control_plan: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    pumps = base_tables.get("pumps", pd.DataFrame())
    boosted_pumps = boosted_tables.get("pumps", pd.DataFrame())
    boosted_lookup = boosted_pumps.set_index("pump_id").to_dict("index") if not boosted_pumps.empty else {}
    rows: list[dict[str, Any]] = []
    plan_lookup = {str(item["control_key"]): item for item in control_plan or []}
    for pump in pumps.to_dict("records"):
        pump_id = str(pump.get("pump_id", ""))
        boosted = boosted_lookup.get(pump_id, {})
        plan = plan_lookup.get(f"pump:{pump_id}", {})
        rows.append(
            {
                "pump_id": pump_id,
                "from_node": str(pump.get("from_node", "")),
                "to_node": str(pump.get("to_node", "")),
                "status": str(pump.get("status", "on")),
                "current_head_gain_m": round(float(pump.get("base_head_gain_m", 0.0) or 0.0), 4),
                "recommended_head_gain_m": round(float(boosted.get("base_head_gain_m", pump.get("base_head_gain_m", 0.0)) or 0.0), 4),
                "predicted_flow_lps": round(_pump_flow_lps(pump, pipe_results), 4),
                "recommended_boost_m": round(float(plan.get("recommended_boost_m", 0.0) or 0.0), 4),
                "flow_contribution_percent": round(float(plan.get("flow_contribution_percent", 0.0) or 0.0), 2),
                "optimization_status": str(plan.get("status", "not_selected")),
            }
        )
    return rows


def _node_outflow_lps(node_id: str, pipe_results: pd.DataFrame) -> float:
    if pipe_results.empty:
        return 0.0
    outflow = 0.0
    for pipe in pipe_results.to_dict("records"):
        flow = float(pipe.get("flow_lps", 0.0) or 0.0)
        if str(pipe.get("from_node", "")) == node_id:
            outflow += flow
        if str(pipe.get("to_node", "")) == node_id:
            outflow -= flow
    return max(outflow, 0.0)


def _pump_flow_lps(pump: Mapping[str, Any], pipe_results: pd.DataFrame) -> float:
    if pipe_results.empty:
        return 0.0
    pump_id = str(pump.get("pump_id", ""))
    from_node = str(pump.get("from_node", ""))
    to_node = str(pump.get("to_node", ""))
    for pipe in pipe_results.to_dict("records"):
        if str(pipe.get("pipe_id", "")) == f"PUMP_{pump_id}":
            return float(pipe.get("flow_lps", 0.0) or 0.0)
    for pipe in pipe_results.to_dict("records"):
        if str(pipe.get("from_node", "")) == from_node and str(pipe.get("to_node", "")) == to_node:
            return float(pipe.get("flow_lps", 0.0) or 0.0)
        if str(pipe.get("from_node", "")) == to_node and str(pipe.get("to_node", "")) == from_node:
            return -float(pipe.get("flow_lps", 0.0) or 0.0)
    return 0.0
