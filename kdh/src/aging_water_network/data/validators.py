"""Validation checks for generated or user-provided mock water-network tables."""

from __future__ import annotations

from typing import Dict, List

import networkx as nx
import pandas as pd

REQUIRED_COLUMNS = {
    "nodes": {"node_id", "x", "y", "elevation_m", "base_demand_lps", "node_type", "dma_id"},
    "pipes": {
        "pipe_id",
        "from_node",
        "to_node",
        "length_m",
        "diameter_mm",
        "material",
        "install_year",
        "bend_count",
        "valve_count",
        "repair_count",
        "leak_history_count",
        "soil_ph",
        "soil_resistivity_ohm_cm",
        "traffic_load_index",
        "burst_history_count",
    },
    "valves": {
        "valve_id",
        "pipe_id",
        "valve_type",
        "status",
        "operation_count_last_year",
        "minor_loss_k",
    },
    "pumps": {"pump_id", "from_node", "to_node", "status", "base_head_gain_m", "speed_multiplier"},
    "reservoirs": {"reservoir_id", "node_id", "head_m"},
    "tanks": {"tank_id", "node_id", "min_level_m", "max_level_m", "initial_level_m"},
    "sensors": {
        "sensor_id",
        "node_or_pipe_id",
        "sensor_type",
        "location_type",
        "noise_std",
        "last_calibrated_date",
    },
    "sensor_timeseries": {"timestamp", "sensor_id", "value"},
    "demand_patterns": {"pattern_id", "hour", "multiplier"},
    "households": {
        "household_id",
        "node_id",
        "dma_id",
        "customer_type",
        "occupants",
        "base_demand_lps",
        "peaking_factor",
    },
    "household_demand_timeseries": {"timestamp", "household_id", "demand_lps"},
}


def validate_required_columns(tables: Dict[str, pd.DataFrame]) -> List[str]:
    errors: List[str] = []
    for table_name, required in REQUIRED_COLUMNS.items():
        if table_name not in tables:
            errors.append(f"missing table: {table_name}")
            continue
        missing = sorted(required - set(tables[table_name].columns))
        if missing:
            errors.append(f"{table_name} missing columns: {', '.join(missing)}")
    return errors


def validate_ids_and_geometry(tables: Dict[str, pd.DataFrame]) -> List[str]:
    errors: List[str] = []
    nodes = tables["nodes"]
    pipes = tables["pipes"]
    valves = tables["valves"]
    reservoirs = tables["reservoirs"]

    for table_name, id_column in [
        ("nodes", "node_id"),
        ("pipes", "pipe_id"),
        ("valves", "valve_id"),
        ("reservoirs", "reservoir_id"),
    ]:
        frame = tables[table_name]
        if frame[id_column].duplicated().any():
            errors.append(f"{table_name} contains duplicate {id_column}")

    node_ids = set(nodes["node_id"])
    missing_from = sorted(set(pipes["from_node"]) - node_ids)
    missing_to = sorted(set(pipes["to_node"]) - node_ids)
    if missing_from or missing_to:
        errors.append(f"pipe endpoints missing from nodes: {missing_from + missing_to}")

    missing_valve_pipes = sorted(set(valves["pipe_id"]) - set(pipes["pipe_id"]))
    if missing_valve_pipes:
        errors.append(f"valves reference missing pipes: {missing_valve_pipes}")

    missing_reservoir_nodes = sorted(set(reservoirs["node_id"]) - node_ids)
    if missing_reservoir_nodes:
        errors.append(f"reservoirs reference missing nodes: {missing_reservoir_nodes}")

    if "households" in tables and not tables["households"].empty:
        households = tables["households"]
        missing_household_nodes = sorted(set(households["node_id"]) - node_ids)
        if missing_household_nodes:
            errors.append(f"households reference missing nodes: {missing_household_nodes}")
        if households["household_id"].duplicated().any():
            errors.append("households contains duplicate household_id")
        if (households["base_demand_lps"] < 0).any():
            errors.append("households contain negative base_demand_lps")

    if "household_demand_timeseries" in tables and not tables["household_demand_timeseries"].empty:
        demand_ts = tables["household_demand_timeseries"]
        household_ids = set(tables.get("households", pd.DataFrame()).get("household_id", []))
        missing_households = sorted(set(demand_ts["household_id"]) - household_ids)
        if missing_households:
            errors.append(f"household demand references missing households: {missing_households[:5]}")
        if (demand_ts["demand_lps"] < 0).any():
            errors.append("household demand timeseries contains negative demand_lps")

    if (pipes["length_m"] <= 0).any():
        errors.append("pipes contain non-positive length_m")
    if (pipes["diameter_mm"] <= 0).any():
        errors.append("pipes contain non-positive diameter_mm")
    if not pipes["install_year"].between(1900, 2026).all():
        errors.append("pipes contain implausible install_year")
    return errors


def validate_connected_network(tables: Dict[str, pd.DataFrame]) -> List[str]:
    graph = nx.Graph()
    graph.add_nodes_from(tables["nodes"]["node_id"].tolist())
    graph.add_edges_from(tables["pipes"][["from_node", "to_node"]].itertuples(index=False, name=None))
    if graph.number_of_nodes() == 0:
        return ["network graph is empty"]
    if not nx.is_connected(graph):
        return ["network graph is not connected"]
    return []


def collect_validation_errors(tables: Dict[str, pd.DataFrame]) -> List[str]:
    errors = validate_required_columns(tables)
    if errors:
        return errors
    errors.extend(validate_ids_and_geometry(tables))
    errors.extend(validate_connected_network(tables))
    return errors


def validate_mock_data(tables: Dict[str, pd.DataFrame]) -> None:
    errors = collect_validation_errors(tables)
    if errors:
        raise ValueError("Invalid mock data: " + "; ".join(errors))
