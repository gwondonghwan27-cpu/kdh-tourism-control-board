from __future__ import annotations

import pytest

from aging_water_network.aging.risk import estimate_burst_probability, estimate_leak_probability
from aging_water_network.aging.roughness import (
    adjust_roughness_by_aging,
    estimate_minor_loss_k,
    hydraulic_params_for_pipe,
)


def test_higher_aging_score_decreases_adjusted_roughness_c() -> None:
    low_aging = adjust_roughness_by_aging("cast_iron", 0.1)
    high_aging = adjust_roughness_by_aging("cast_iron", 0.8)

    assert high_aging < low_aging
    assert high_aging == pytest.approx(79.2)


def test_higher_bend_and_valve_count_increases_minor_loss_k() -> None:
    simple = estimate_minor_loss_k(0.2, bend_count=0, valve_minor_loss_k=0.0)
    complex_pipe = estimate_minor_loss_k(0.2, bend_count=4, valve_minor_loss_k=[0.5, 1.0])

    assert complex_pipe > simple
    assert complex_pipe == pytest.approx(simple + 0.8 + 1.5)


def test_higher_aging_score_increases_leak_probability() -> None:
    assert estimate_leak_probability(0.9) > estimate_leak_probability(0.1)


def test_burst_risk_increases_nonlinearly_with_aging_score() -> None:
    low = estimate_burst_probability(0.2)
    mid = estimate_burst_probability(0.4)
    high = estimate_burst_probability(0.8)

    assert mid - low < high - mid
    assert high > mid > low


def test_hydraulic_params_for_pipe_combines_mappings() -> None:
    params = hydraulic_params_for_pipe(
        {"pipe_id": "P9", "material": "steel", "bend_count": 2, "leak_history_count": 2},
        aging_score=0.5,
        valve_minor_loss_k=1.0,
        pressure_stress_component=0.25,
    )

    assert params.pipe_id == "P9"
    assert params.adjusted_roughness_c < params.base_roughness_c
    assert params.minor_loss_k == pytest.approx(0.4 + 1.0 + 0.75)
    assert params.leak_probability > 0.005
    assert params.burst_probability > 0.001
