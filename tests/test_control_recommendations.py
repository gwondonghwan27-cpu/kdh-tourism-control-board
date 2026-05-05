from __future__ import annotations

import pandas as pd

from aging_water_network.control.controller import (
    rank_control_recommendations,
    run_fallback_hydraulic_simulation,
)


def _tables(
    source_head: float = 35.0, aged_pipe_length_m: float = 320.0
) -> dict[str, pd.DataFrame]:
    return {
        "nodes": pd.DataFrame(
            [
                {
                    "node_id": "R1",
                    "x": 0,
                    "y": 0,
                    "elevation_m": 30.0,
                    "base_demand_lps": 0.0,
                    "node_type": "reservoir",
                    "dma_id": "SRC",
                },
                {
                    "node_id": "J1",
                    "x": 1,
                    "y": 0,
                    "elevation_m": 30.0,
                    "base_demand_lps": 1.0,
                    "node_type": "junction",
                    "dma_id": "A",
                },
                {
                    "node_id": "J2",
                    "x": 2,
                    "y": 0,
                    "elevation_m": 30.0,
                    "base_demand_lps": 2.0,
                    "node_type": "junction",
                    "dma_id": "A",
                },
            ]
        ),
        "pipes": pd.DataFrame(
            [
                {
                    "pipe_id": "P1",
                    "from_node": "R1",
                    "to_node": "J1",
                    "length_m": 100.0,
                    "diameter_mm": 300.0,
                    "material": "ductile_iron",
                    "install_year": 2015,
                    "bend_count": 0,
                    "valve_count": 1,
                    "repair_count": 0,
                    "leak_history_count": 0,
                    "soil_ph": 7.0,
                    "soil_resistivity_ohm_cm": 3000,
                    "traffic_load_index": 0.1,
                    "burst_history_count": 0,
                },
                {
                    "pipe_id": "P2",
                    "from_node": "J1",
                    "to_node": "J2",
                    "length_m": aged_pipe_length_m,
                    "diameter_mm": 150.0,
                    "material": "cast_iron",
                    "install_year": 1960,
                    "bend_count": 2,
                    "valve_count": 0,
                    "repair_count": 4,
                    "leak_history_count": 2,
                    "soil_ph": 5.8,
                    "soil_resistivity_ohm_cm": 800,
                    "traffic_load_index": 0.8,
                    "burst_history_count": 1,
                },
            ]
        ),
        "valves": pd.DataFrame(
            [
                {
                    "valve_id": "V1",
                    "pipe_id": "P1",
                    "valve_type": "isolation",
                    "status": "partially_open",
                    "operation_count_last_year": 10,
                    "minor_loss_k": 1.5,
                }
            ]
        ),
        "pumps": pd.DataFrame(
            [
                {
                    "pump_id": "PU1",
                    "from_node": "R1",
                    "to_node": "J1",
                    "status": "on",
                    "base_head_gain_m": 0.0,
                    "speed_multiplier": 1.0,
                }
            ]
        ),
        "reservoirs": pd.DataFrame(
            [{"reservoir_id": "RES1", "node_id": "R1", "head_m": source_head}]
        ),
        "tanks": pd.DataFrame(
            columns=["tank_id", "node_id", "min_level_m", "max_level_m", "initial_level_m"]
        ),
        "sensors": pd.DataFrame(),
        "sensor_timeseries": pd.DataFrame(),
        "demand_patterns": pd.DataFrame(),
    }


def test_recommendations_rank_pressure_recovery_first() -> None:
    recommendations = rank_control_recommendations(
        tables=_tables(source_head=30.0, aged_pipe_length_m=120.0),
        simulator=run_fallback_hydraulic_simulation,
        max_recommendations=3,
    )

    assert recommendations
    assert recommendations[0].action_id == "source_head_+7.5m"
    assert recommendations[0].score >= recommendations[-1].score
    assert "15 m" not in " ".join(recommendations[0].risks)


def test_overpressure_on_aged_pipes_penalizes_head_increase() -> None:
    recommendations = rank_control_recommendations(
        tables=_tables(source_head=78.0, aged_pipe_length_m=120.0),
        simulator=run_fallback_hydraulic_simulation,
        max_recommendations=5,
    )
    top_ids = [item.action_id for item in recommendations[:2]]

    assert "source_head_+7.5m" not in top_ids
    assert any(item.action_id.startswith("source_head_-") for item in recommendations[:3])
