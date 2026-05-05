#!/usr/bin/env python
"""CLI wrapper for deterministic mock data generation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aging_water_network.data.mock_generator import main


if __name__ == "__main__":
    main()
