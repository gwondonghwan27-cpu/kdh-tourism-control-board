"""CSV loading helpers for the local mock data contract."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

TABLE_FILES = {
    "nodes": "nodes.csv",
    "pipes": "pipes.csv",
    "valves": "valves.csv",
    "pumps": "pumps.csv",
    "reservoirs": "reservoirs.csv",
    "tanks": "tanks.csv",
    "sensors": "sensors.csv",
    "sensor_timeseries": "sensor_timeseries.csv",
    "demand_patterns": "demand_patterns.csv",
    "households": "households.csv",
    "household_demand_timeseries": "household_demand_timeseries.csv",
}


def load_table(data_dir: str | Path, table_name: str) -> pd.DataFrame:
    data_path = Path(data_dir)
    try:
        file_name = TABLE_FILES[table_name]
    except KeyError as exc:
        raise KeyError(f"Unknown table: {table_name}") from exc

    path = data_path / file_name
    if not path.exists():
        raise FileNotFoundError(f"Missing required data table: {path}")
    return pd.read_csv(path)


def load_mock_data(data_dir: str | Path) -> Dict[str, pd.DataFrame]:
    """Load every expected CSV table from a mock data directory."""

    return {name: load_table(data_dir, name) for name in TABLE_FILES}


def ensure_mock_data(data_dir: str | Path, scenario: str = "aging_headloss") -> Dict[str, pd.DataFrame]:
    """Load existing mock data, generating it first if the directory is incomplete."""

    data_path = Path(data_dir)
    missing = [file_name for file_name in TABLE_FILES.values() if not (data_path / file_name).exists()]
    if missing:
        from aging_water_network.data.mock_generator import generate_mock_network

        generate_mock_network(data_path, scenario=scenario)
    return load_mock_data(data_path)
