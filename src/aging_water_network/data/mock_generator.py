"""Deterministic synthetic water-network generator."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd

from aging_water_network.data.validators import validate_mock_data

SCENARIOS = ("normal", "aging_headloss", "suspected_leak", "overpressure_aged")


def _junction_id(row: int, col: int, cols: int) -> str:
    return f"J{row * cols + col + 1}"


def _scenario_source_head(scenario: str) -> float:
    return {
        "normal": 76.0,
        "aging_headloss": 45.0,
        "suspected_leak": 66.0,
        "overpressure_aged": 90.0,
    }.get(scenario, 64.0)


def _iter_grid_edges(rows: int, cols: int) -> Iterable[Tuple[str, str, str]]:
    for row in range(rows):
        for col in range(cols - 1):
            yield "horizontal", _junction_id(row, col, cols), _junction_id(row, col + 1, cols)
    for row in range(rows - 1):
        for col in range(cols):
            yield "vertical", _junction_id(row, col, cols), _junction_id(row + 1, col, cols)


def _daily_demand_multiplier(hour: float, household_phase: float = 0.0) -> float:
    morning = np.exp(-0.5 * ((hour - (7.2 + household_phase)) / 1.35) ** 2)
    evening = np.exp(-0.5 * ((hour - (19.0 - household_phase * 0.5)) / 1.7) ** 2)
    midday = np.exp(-0.5 * ((hour - 12.4) / 3.0) ** 2)
    night_reduction = 0.58 + 0.08 * np.cos((hour - 3.0) / 24.0 * 2.0 * np.pi)
    return float(np.clip(night_reduction + 0.42 * morning + 0.52 * evening + 0.12 * midday, 0.25, 2.4))


def _build_household_tables(
    nodes: pd.DataFrame,
    scenario: str,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    households: list[dict[str, object]] = []
    demand_rows: list[dict[str, object]] = []
    timestamps = pd.date_range("2026-01-01 00:00:00", periods=96, freq="15min")

    for _, node in nodes[nodes["node_type"].eq("junction")].iterrows():
        node_id = str(node["node_id"])
        base_node_demand = float(node["base_demand_lps"])
        household_count = int(np.clip(round(base_node_demand * 2.4 + rng.integers(1, 4)), 3, 8))
        weights = rng.dirichlet(np.ones(household_count))
        for idx in range(household_count):
            household_id = f"H_{node_id}_{idx + 1}"
            customer_type = "residential"
            if idx == 0 and base_node_demand > 2.4:
                customer_type = "small_commercial"
            occupants = int(rng.integers(1, 6)) if customer_type == "residential" else int(rng.integers(4, 12))
            peaking_factor = round(float(rng.uniform(1.25, 2.25)), 3)
            base_demand = round(float(base_node_demand * weights[idx]), 5)
            households.append(
                {
                    "household_id": household_id,
                    "node_id": node_id,
                    "dma_id": node["dma_id"],
                    "customer_type": customer_type,
                    "occupants": occupants,
                    "base_demand_lps": base_demand,
                    "peaking_factor": peaking_factor,
                }
            )
            phase = float(rng.normal(0.0, 0.35))
            for ts in timestamps:
                hour = ts.hour + ts.minute / 60.0
                multiplier = _daily_demand_multiplier(hour, phase)
                if customer_type == "small_commercial":
                    workday = np.exp(-0.5 * ((hour - 13.0) / 3.4) ** 2)
                    multiplier = 0.45 + 0.95 * workday
                stochastic = float(rng.lognormal(mean=0.0, sigma=0.08))
                demand = base_demand * multiplier * stochastic
                if scenario == "suspected_leak" and node_id in {"J16", "J20", "J24"} and ts.hour >= 18:
                    demand += base_demand * 0.55
                demand_rows.append(
                    {
                        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "household_id": household_id,
                        "demand_lps": round(float(max(demand, 0.0)), 5),
                    }
                )

    return pd.DataFrame(households), pd.DataFrame(demand_rows)


def _pipe_profile(index: int, from_node: str, to_node: str, kind: str, scenario: str) -> Dict[str, object]:
    materials = ["ductile_iron", "PVC", "HDPE", "cast_iron", "steel", "concrete"]
    material = materials[index % len(materials)]
    install_year = 1988 + (index * 7) % 32
    diameter_mm = 260 + (index % 4) * 40
    length_m = 145 + (index % 5) * 28
    bend_count = index % 3
    repair_count = 0 if index % 4 else 1
    leak_count = 0 if index % 5 else 1
    burst_count = 0
    soil_ph = 6.4 + (index % 7) * 0.18
    resistivity = 1300 + (index % 9) * 420
    traffic = round(0.15 + (index % 6) * 0.13, 2)

    in_aged_corridor = from_node in {"J9", "J10", "J11", "J15", "J16", "J17"} or to_node in {
        "J10",
        "J11",
        "J16",
        "J17",
        "J22",
        "J23",
    }
    near_source = from_node in {"R1", "J1", "J2", "J7"} or to_node in {"J1", "J2", "J7", "J8"}

    if scenario in {"aging_headloss", "suspected_leak"} and in_aged_corridor:
        material = "cast_iron"
        install_year = 1965 + (index % 5)
        diameter_mm = 150 if kind == "horizontal" else 170
        length_m += 80
        bend_count += 2
        repair_count = max(repair_count, 4)
        leak_count = max(leak_count, 2)
        burst_count = 1 if index % 3 == 0 else 0
        soil_ph = 5.8
        resistivity = 850
        traffic = 0.88

    if scenario == "overpressure_aged" and near_source:
        material = "cast_iron"
        install_year = 1962 + (index % 4)
        repair_count = max(repair_count, 3)
        leak_count = max(leak_count, 2)
        bend_count += 1
        soil_ph = 5.9
        resistivity = 900
        traffic = 0.78

    return {
        "pipe_id": f"P{index}",
        "from_node": from_node,
        "to_node": to_node,
        "length_m": float(length_m),
        "diameter_mm": float(diameter_mm),
        "material": material,
        "install_year": int(install_year),
        "bend_count": int(bend_count),
        "valve_count": 0,
        "repair_count": int(repair_count),
        "leak_history_count": int(leak_count),
        "soil_ph": float(soil_ph),
        "soil_resistivity_ohm_cm": float(resistivity),
        "traffic_load_index": float(min(traffic, 1.0)),
        "burst_history_count": int(burst_count),
    }


def build_mock_tables(nodes: int = 30, scenario: str = "aging_headloss", seed: int = 42) -> Dict[str, pd.DataFrame]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}. Expected one of {SCENARIOS}.")

    rng = np.random.default_rng(seed)
    cols = 6
    rows = max(4, int(np.ceil(nodes / cols)))
    junction_count = rows * cols

    node_rows: List[Dict[str, object]] = [
        {
            "node_id": "R1",
            "x": -120.0,
            "y": 0.0,
            "elevation_m": 38.0,
            "base_demand_lps": 0.0,
            "node_type": "reservoir",
            "dma_id": "SOURCE",
        }
    ]
    for row in range(rows):
        for col in range(cols):
            node_id = _junction_id(row, col, cols)
            elevation = 28.5 + (rows - row) * 0.85 + col * 0.18 + rng.normal(0, 0.15)
            demand = 0.9 + (row / max(rows - 1, 1)) * 0.8 + (col / max(cols - 1, 1)) * 0.7
            if scenario in {"aging_headloss", "suspected_leak"} and row >= 2 and col >= 2:
                demand *= 1.35
            node_rows.append(
                {
                    "node_id": node_id,
                    "x": float(col * 110),
                    "y": float(row * 95),
                    "elevation_m": round(float(elevation), 2),
                    "base_demand_lps": round(float(demand), 2),
                    "node_type": "junction",
                    "dma_id": "DMA_A" if row < rows / 2 else "DMA_B",
                }
            )

    pipe_rows: List[Dict[str, object]] = [
        {
            "pipe_id": "P1",
            "from_node": "R1",
            "to_node": "J1",
            "length_m": 90.0,
            "diameter_mm": 500.0,
            "material": "ductile_iron",
            "install_year": 2012,
            "bend_count": 0,
            "valve_count": 0,
            "repair_count": 0,
            "leak_history_count": 0,
            "soil_ph": 7.1,
            "soil_resistivity_ohm_cm": 3200.0,
            "traffic_load_index": 0.2,
            "burst_history_count": 0,
        }
    ]
    for idx, (kind, from_node, to_node) in enumerate(_iter_grid_edges(rows, cols), start=2):
        pipe_rows.append(_pipe_profile(idx, from_node, to_node, kind, scenario))

    pipes = pd.DataFrame(pipe_rows)
    valve_pipe_ids = pipes.loc[pipes["pipe_id"].isin(["P4", "P9", "P15", "P22", "P29", "P35", "P42", "P48"]), "pipe_id"].tolist()
    if len(valve_pipe_ids) < 8:
        valve_pipe_ids = pipes["pipe_id"].iloc[3::6].head(8).tolist()

    valve_rows = []
    for idx, pipe_id in enumerate(valve_pipe_ids, start=1):
        status = "open"
        valve_type = "isolation"
        minor_loss = 0.25 + (idx % 3) * 0.25
        operations = 10 + idx * 7
        if idx in {3, 6}:
            valve_type = "PRV"
            minor_loss = 1.4
            operations = 180 + idx * 8
        if scenario == "suspected_leak" and idx == 4:
            status = "partially_open"
            minor_loss = 2.0
        valve_rows.append(
            {
                "valve_id": f"V{idx}",
                "pipe_id": pipe_id,
                "valve_type": valve_type,
                "status": status,
                "operation_count_last_year": operations,
                "minor_loss_k": minor_loss,
            }
        )
    valves = pd.DataFrame(valve_rows)
    pipes.loc[pipes["pipe_id"].isin(valves["pipe_id"]), "valve_count"] = 1

    pressure_sensor_nodes = ["J4", "J8", "J12", "J16", "J20", "J24", "J28", f"J{junction_count}"]
    pressure_sensor_nodes = [node for node in pressure_sensor_nodes if node in set(pd.DataFrame(node_rows)["node_id"])]
    flow_sensor_pipes = ["P10", "P25"]
    sensor_rows = []
    for idx, node_id in enumerate(pressure_sensor_nodes, start=1):
        sensor_rows.append(
            {
                "sensor_id": f"S{idx}",
                "node_or_pipe_id": node_id,
                "sensor_type": "pressure",
                "location_type": "node",
                "noise_std": 0.25,
                "last_calibrated_date": "2026-01-01",
            }
        )
    start = len(sensor_rows) + 1
    for offset, pipe_id in enumerate(flow_sensor_pipes):
        sensor_rows.append(
            {
                "sensor_id": f"S{start + offset}",
                "node_or_pipe_id": pipe_id,
                "sensor_type": "flow",
                "location_type": "pipe",
                "noise_std": 0.12,
                "last_calibrated_date": "2026-01-01",
            }
        )
    sensors = pd.DataFrame(sensor_rows)

    timeseries_rows = []
    timestamps = pd.date_range("2026-01-01 00:00:00", periods=12, freq="5min")
    for _, sensor in sensors.iterrows():
        for step, timestamp in enumerate(timestamps):
            base_value = 28.0 + np.sin(step / 2.5) * 0.7
            if sensor["sensor_type"] == "flow":
                base_value = 9.0 + np.cos(step / 3.0) * 0.4
            if scenario == "suspected_leak":
                if sensor["node_or_pipe_id"] in {"J16", "J20", "J24"} and sensor["sensor_type"] == "pressure":
                    base_value -= 6.5 if step >= 8 else 2.0
                if sensor["node_or_pipe_id"] == "P25" and sensor["sensor_type"] == "flow":
                    base_value += 4.5 if step >= 8 else 1.0
            timeseries_rows.append(
                {
                    "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "sensor_id": sensor["sensor_id"],
                    "value": round(float(base_value + rng.normal(0, sensor["noise_std"])), 3),
                }
            )

    households, household_demand_timeseries = _build_household_tables(
        pd.DataFrame(node_rows), scenario, rng
    )

    tables = {
        "nodes": pd.DataFrame(node_rows),
        "pipes": pipes,
        "valves": valves,
        "pumps": pd.DataFrame(
            [
                {
                    "pump_id": "PU1",
                    "from_node": "R1",
                    "to_node": "J1",
                    "status": "on",
                    "base_head_gain_m": 3.0 if scenario != "overpressure_aged" else 6.0,
                    "speed_multiplier": 1.0,
                }
            ]
        ),
        "reservoirs": pd.DataFrame(
            [{"reservoir_id": "RES1", "node_id": "R1", "head_m": _scenario_source_head(scenario)}]
        ),
        "tanks": pd.DataFrame(
            columns=["tank_id", "node_id", "min_level_m", "max_level_m", "initial_level_m"]
        ),
        "sensors": sensors,
        "sensor_timeseries": pd.DataFrame(timeseries_rows),
        "demand_patterns": pd.DataFrame(
            [
                {"pattern_id": "weekday", "hour": hour, "multiplier": round(0.78 + 0.32 * np.sin((hour - 6) / 24 * 2 * np.pi) ** 2, 3)}
                for hour in range(24)
            ]
        ),
        "households": households,
        "household_demand_timeseries": household_demand_timeseries,
    }
    validate_mock_data(tables)
    return tables


def generate_mock_network(
    out: str | Path = "data/mock",
    nodes: int = 30,
    scenario: str = "aging_headloss",
    seed: int = 42,
) -> Dict[str, pd.DataFrame]:
    """Generate deterministic mock CSV files and return the in-memory tables."""

    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    tables = build_mock_tables(nodes=nodes, scenario=scenario, seed=seed)
    for name, frame in tables.items():
        frame.to_csv(out_path / f"{name}.csv", index=False)
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mock aging-aware water network CSV data.")
    parser.add_argument("--out", default="data/mock", help="Output directory for CSV tables.")
    parser.add_argument("--nodes", type=int, default=30, help="Minimum number of demand junctions.")
    parser.add_argument("--scenario", choices=SCENARIOS, default="aging_headloss")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    tables = generate_mock_network(args.out, nodes=args.nodes, scenario=args.scenario, seed=args.seed)
    print("Generated mock network:")
    print(f"- nodes: {len(tables['nodes'])}")
    print(f"- pipes: {len(tables['pipes'])}")
    print(f"- valves: {len(tables['valves'])}")
    print(f"- sensors: {len(tables['sensors'])}")
    print(f"- households: {len(tables['households'])}")
    print(f"- household demand rows: {len(tables['household_demand_timeseries'])}")
    print(f"- scenario: {args.scenario}")


if __name__ == "__main__":
    main()
