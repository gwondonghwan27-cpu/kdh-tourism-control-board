"""Leak and burst risk indices derived from pipe aging inputs."""

from __future__ import annotations

from aging_water_network.config import (
    BASE_BURST_PROBABILITY,
    BASE_LEAK_PROBABILITY,
    LEAK_AGING_MULTIPLIER,
)


def clip01(value: float) -> float:
    """Clamp a numeric value to the closed interval [0, 1]."""
    return max(0.0, min(float(value), 1.0))


def estimate_leak_probability(
    aging_score: float,
    *,
    base_leak_probability: float = BASE_LEAK_PROBABILITY,
    aging_multiplier: float = LEAK_AGING_MULTIPLIER,
) -> float:
    """Estimate leak probability from the linear MVP aging formula."""
    return clip01(base_leak_probability + aging_multiplier * clip01(aging_score))


def estimate_burst_probability(
    aging_score: float,
    *,
    pressure_stress_component: float = 0.0,
    leak_history_component: float = 0.0,
    base_burst_probability: float = BASE_BURST_PROBABILITY,
) -> float:
    """Estimate the nonlinear burst risk index from PROJECT_SPEC.md."""
    aging = clip01(aging_score)
    pressure_stress = clip01(pressure_stress_component)
    leak_history = clip01(leak_history_component)
    return clip01(
        base_burst_probability
        + 0.10 * aging**2
        + 0.08 * pressure_stress
        + 0.05 * leak_history
    )
