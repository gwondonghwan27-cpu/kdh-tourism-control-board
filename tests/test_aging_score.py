from __future__ import annotations

import pandas as pd

from aging_water_network.aging.scoring import compute_all_aging_scores, compute_pipe_aging_score


def _pipe(**overrides: object) -> dict[str, object]:
    row = {
        "pipe_id": "P1",
        "from_node": "J1",
        "to_node": "J2",
        "length_m": 100.0,
        "diameter_mm": 250.0,
        "material": "PVC",
        "install_year": 2020,
        "bend_count": 0,
        "valve_count": 0,
        "repair_count": 0,
        "leak_history_count": 0,
        "soil_ph": 7.0,
        "soil_resistivity_ohm_cm": 5000.0,
        "traffic_load_index": 0.0,
        "burst_history_count": 0,
    }
    row.update(overrides)
    return row


def test_new_pvc_scores_lower_than_old_cast_iron() -> None:
    new_pvc = compute_pipe_aging_score(_pipe(pipe_id="PVC"), current_year=2026)
    old_cast_iron = compute_pipe_aging_score(
        _pipe(
            pipe_id="CI",
            material="cast_iron",
            install_year=1960,
            bend_count=4,
            valve_count=2,
            repair_count=4,
            leak_history_count=2,
            soil_ph=5.8,
            soil_resistivity_ohm_cm=900.0,
            traffic_load_index=0.9,
        ),
        current_year=2026,
    )

    assert 0.0 <= new_pvc.aging_score <= 1.0
    assert 0.0 <= old_cast_iron.aging_score <= 1.0
    assert new_pvc.aging_score < 0.25
    assert old_cast_iron.aging_score > 0.70
    assert old_cast_iron.aging_score > new_pvc.aging_score


def test_repair_and_leak_history_increase_score_monotonically() -> None:
    baseline = compute_pipe_aging_score(_pipe()).aging_score
    repaired = compute_pipe_aging_score(_pipe(repair_count=3)).aging_score
    leaky = compute_pipe_aging_score(_pipe(leak_history_count=2)).aging_score
    repaired_and_leaky = compute_pipe_aging_score(
        _pipe(repair_count=3, leak_history_count=2)
    ).aging_score

    assert repaired > baseline
    assert leaky > baseline
    assert repaired_and_leaky > repaired
    assert repaired_and_leaky > leaky


def test_soil_and_traffic_increase_score() -> None:
    baseline = compute_pipe_aging_score(_pipe()).aging_score
    corrosive_soil = compute_pipe_aging_score(
        _pipe(soil_ph=5.5, soil_resistivity_ohm_cm=800.0)
    ).aging_score
    heavy_traffic = compute_pipe_aging_score(_pipe(traffic_load_index=1.0)).aging_score

    assert corrosive_soil > baseline
    assert heavy_traffic > baseline


def test_compute_all_aging_scores_returns_component_columns() -> None:
    frame = pd.DataFrame([_pipe(pipe_id="P1"), _pipe(pipe_id="P2", material="steel")])
    scored = compute_all_aging_scores(frame)

    assert list(scored.columns) == [
        "pipe_id",
        "aging_score",
        "age_component",
        "material_component",
        "repair_component",
        "leak_history_component",
        "geometry_component",
        "soil_component",
        "traffic_component",
        "pressure_stress_component",
        "topology_component",
    ]
    assert scored["aging_score"].between(0.0, 1.0).all()
