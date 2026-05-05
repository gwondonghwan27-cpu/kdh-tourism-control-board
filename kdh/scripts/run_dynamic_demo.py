#!/usr/bin/env python
"""Run dynamic household-demand simulation and minimum source-head search."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aging_water_network.hydraulics.dynamic import run_dynamic_demand_simulation


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dynamic household demand hydraulic demo.")
    parser.add_argument("--data-dir", default="data/mock")
    parser.add_argument("--steps", type=int, default=96, help="Number of 15-minute steps to print.")
    parser.add_argument("--include-minor-losses", action="store_true")
    args = parser.parse_args()

    result = run_dynamic_demand_simulation(
        data_dir=args.data_dir,
        include_minor_losses=args.include_minor_losses,
    )
    summary = result["dynamic_summary"].head(args.steps)
    print("Dynamic demand simulation:")
    print(f"- time steps: {len(result['dynamic_summary'])}")
    print(f"- peak demand: {result['dynamic_summary']['total_demand_lps'].max():.2f} L/s")
    print(
        "- max required pump gain: "
        f"{result['dynamic_summary']['required_pump_head_gain_m'].max():.2f} m"
    )
    print(
        "- hydraulic bound violations: "
        f"{int((~result['dynamic_summary']['within_hydraulic_bounds']).sum())}"
    )
    print(
        summary[
            [
                "timestamp",
                "total_demand_lps",
                "required_source_head_m",
                "required_pump_head_gain_m",
                "min_pressure_head_m",
                "max_pressure_head_m",
                "within_hydraulic_bounds",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()

