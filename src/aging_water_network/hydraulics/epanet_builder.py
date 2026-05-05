"""Build WNTR-compatible network objects, with a lightweight fallback model."""

from __future__ import annotations

from typing import Mapping

import pandas as pd


def _pipe_param_lookup(pipe_params: pd.DataFrame | None) -> dict[str, dict[str, float]]:
    if pipe_params is None or pipe_params.empty:
        return {}
    return {str(row["pipe_id"]): row for row in pipe_params.to_dict("records")}


def build_fallback_model(
    tables: Mapping[str, pd.DataFrame],
    pipe_params: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | str]:
    """Return a plain dict model that mirrors the tables WNTR would consume."""

    params = _pipe_param_lookup(pipe_params)
    pipes = tables["pipes"].copy()
    pipes["roughness_c"] = pipes["pipe_id"].map(lambda pipe_id: params.get(str(pipe_id), {}).get("adjusted_roughness_c", 100.0))
    pipes["minor_loss_k"] = pipes["pipe_id"].map(lambda pipe_id: params.get(str(pipe_id), {}).get("minor_loss_k", 0.0))
    return {
        "engine": "fallback",
        "nodes": tables["nodes"].copy(),
        "pipes": pipes,
        "valves": tables.get("valves", pd.DataFrame()).copy(),
        "pumps": tables.get("pumps", pd.DataFrame()).copy(),
        "reservoirs": tables.get("reservoirs", pd.DataFrame()).copy(),
        "tanks": tables.get("tanks", pd.DataFrame()).copy(),
    }


def build_wntr_model(
    tables: Mapping[str, pd.DataFrame],
    pipe_params: pd.DataFrame | None = None,
):
    """Build a ``wntr.network.WaterNetworkModel`` when WNTR is installed."""

    try:
        import wntr  # type: ignore
    except ImportError as exc:
        raise RuntimeError("WNTR is not installed; use build_fallback_model or run fallback simulation.") from exc

    params = _pipe_param_lookup(pipe_params)
    wn = wntr.network.WaterNetworkModel()

    reservoirs = tables.get("reservoirs", pd.DataFrame())
    reservoir_nodes = set(reservoirs.get("node_id", pd.Series(dtype=str)).astype(str).tolist())
    for row in reservoirs.to_dict("records"):
        wn.add_reservoir(str(row["node_id"]), base_head=float(row["head_m"]))

    for row in tables["nodes"].to_dict("records"):
        node_id = str(row["node_id"])
        if node_id in reservoir_nodes:
            continue
        wn.add_junction(
            node_id,
            base_demand=float(row.get("base_demand_lps", 0.0)) / 1000.0,
            elevation=float(row.get("elevation_m", 0.0)),
        )

    for row in tables["pipes"].to_dict("records"):
        pipe_id = str(row["pipe_id"])
        pipe_param = params.get(pipe_id, {})
        wn.add_pipe(
            pipe_id,
            str(row["from_node"]),
            str(row["to_node"]),
            length=float(row["length_m"]),
            diameter=float(row["diameter_mm"]) / 1000.0,
            roughness=float(pipe_param.get("adjusted_roughness_c", 100.0)),
            minor_loss=float(pipe_param.get("minor_loss_k", 0.0)),
        )

    for row in tables.get("pumps", pd.DataFrame()).to_dict("records"):
        if str(row.get("status", "on")).lower() == "off":
            continue
        wn.add_pump(
            str(row["pump_id"]),
            str(row["from_node"]),
            str(row["to_node"]),
            pump_type="POWER",
            pump_parameter=max(float(row.get("base_head_gain_m", 0.0)), 0.1) * 9.81,
        )

    return wn


def build_epanet_model(
    tables: Mapping[str, pd.DataFrame],
    pipe_params: pd.DataFrame | None = None,
    prefer_wntr: bool = True,
):
    """Build a WNTR model when possible, otherwise return the fallback model."""

    if prefer_wntr:
        try:
            return build_wntr_model(tables, pipe_params=pipe_params)
        except RuntimeError:
            pass
    return build_fallback_model(tables, pipe_params=pipe_params)
