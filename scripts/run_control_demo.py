#!/usr/bin/env python
"""Print ranked pressure-control recommendations for a mock network."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aging_water_network.control.controller import rank_control_recommendations


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the aging-aware control recommendation demo.")
    parser.add_argument("--data-dir", default="data/mock")
    parser.add_argument("--scenario", default="aging_headloss")
    parser.add_argument("--max-recommendations", type=int, default=5)
    args = parser.parse_args()

    recommendations = rank_control_recommendations(
        data_dir=args.data_dir,
        max_recommendations=args.max_recommendations,
    )
    for idx, recommendation in enumerate(recommendations, start=1):
        print(f"{idx}. {recommendation.description}")
        print(f"   score={recommendation.score:.3f} effect={recommendation.expected_effect}")
        if recommendation.risks:
            print(f"   risks={' | '.join(recommendation.risks)}")


if __name__ == "__main__":
    main()
