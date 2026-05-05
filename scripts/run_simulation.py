#!/usr/bin/env python
"""Run a hydraulic simulation, using the worker simulator if present."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aging_water_network.control.controller import run_fallback_hydraulic_simulation
from aging_water_network.control.evaluator import extract_node_pressures
from aging_water_network.data.loaders import ensure_mock_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the aging-water-network hydraulic simulation."
    )
    parser.add_argument("--data-dir", default="data/mock")
    parser.add_argument("--scenario", default="aging_headloss")
    parser.add_argument("--source-head-delta-m", type=float, default=0.0)
    args = parser.parse_args()

    tables = ensure_mock_data(args.data_dir, scenario=args.scenario)
    try:
        from aging_water_network.hydraulics.simulator import run_hydraulic_simulation

        if args.source_head_delta_m:
            result = run_fallback_hydraulic_simulation(
                data_dir=args.data_dir,
                tables=tables,
                source_head_delta_m=args.source_head_delta_m,
                valve_status_overrides={},
            )
        else:
            result = run_hydraulic_simulation(data_dir=args.data_dir, tables=tables)
    except Exception:
        result = run_fallback_hydraulic_simulation(
            data_dir=args.data_dir,
            tables=tables,
            source_head_delta_m=args.source_head_delta_m,
            valve_status_overrides={},
        )

    pressures = extract_node_pressures(result)
    demand_pressures = pressures[pressures["node_id"].astype(str).str.startswith("J")]
    print(f"Simulated nodes: {len(pressures)}")
    print(f"Minimum demand pressure head: {demand_pressures['pressure_head_m'].min():.2f} m")
    print(f"Maximum demand pressure head: {demand_pressures['pressure_head_m'].max():.2f} m")


if __name__ == "__main__":
    main()
