"""EPANET-style pipe head-loss formulas.

The functions in this module follow the EPANET hydraulic relation

    hL = r q |q|^(n - 1) + m q |q|

where ``r`` is the friction resistance coefficient, ``n`` is the
formula exponent, and ``m`` is the velocity-based minor-loss coefficient.
All public functions use SI dashboard units: flow in L/s, length in m,
diameter in mm, and head loss in m.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

GRAVITY_M_S2 = 9.80665
KINEMATIC_VISCOSITY_M2_S = 1.004e-6
MIN_DIAMETER_M = 1e-6
MIN_ROUGHNESS = 1e-9

HeadlossFormula = Literal["H-W", "D-W", "C-M", "HW", "DW", "CM", "hazen-williams", "darcy-weisbach", "chezy-manning"]


@dataclass(frozen=True)
class HeadlossParts:
    """Computed pipe head-loss components for a single flow value."""

    headloss_m: float
    friction_headloss_m: float
    minor_headloss_m: float
    resistance: float
    exponent: float
    minor_resistance: float
    friction_factor: float | None = None


def normalize_headloss_formula(formula: str | None) -> str:
    """Return EPANET's short formula key."""

    value = str(formula or "H-W").strip().upper().replace("_", "-")
    aliases = {
        "HW": "H-W",
        "H-W": "H-W",
        "HAZEN-WILLIAMS": "H-W",
        "DW": "D-W",
        "D-W": "D-W",
        "DARCY-WEISBACH": "D-W",
        "CM": "C-M",
        "C-M": "C-M",
        "CHEZY-MANNING": "C-M",
    }
    return aliases.get(value, "H-W")


def epanet_pipe_resistance(
    length_m: float,
    diameter_mm: float,
    roughness: float,
    *,
    formula: str | None = "H-W",
    flow_lps: float = 0.0,
    viscosity_m2_s: float = KINEMATIC_VISCOSITY_M2_S,
) -> tuple[float, float, float | None]:
    """Return ``(r, n, f)`` for EPANET's pipe head-loss equation."""

    length = max(float(length_m), 0.0)
    diameter_m = max(float(diameter_mm) / 1000.0, MIN_DIAMETER_M)
    roughness_value = max(float(roughness), MIN_ROUGHNESS)
    formula_key = normalize_headloss_formula(formula)

    if formula_key == "D-W":
        friction_factor = darcy_weisbach_friction_factor(
            flow_lps,
            diameter_mm,
            roughness_value,
            viscosity_m2_s=viscosity_m2_s,
        )
        return 0.0827 * friction_factor * length / diameter_m**5, 2.0, friction_factor
    if formula_key == "C-M":
        return 10.294 * roughness_value**2 * length / diameter_m**5.333, 2.0, None
    return 10.67 * length / (roughness_value**1.852 * diameter_m**4.871), 1.852, None


def epanet_minor_loss_resistance(diameter_mm: float, minor_loss_k: float = 0.0) -> float:
    """Return EPANET's SI minor-loss coefficient ``m`` for ``m q |q|``."""

    diameter_m = max(float(diameter_mm) / 1000.0, MIN_DIAMETER_M)
    return 8.0 * max(float(minor_loss_k), 0.0) / (GRAVITY_M_S2 * np.pi**2 * diameter_m**4)


def darcy_weisbach_friction_factor(
    flow_lps: float,
    diameter_mm: float,
    roughness_mm: float,
    *,
    viscosity_m2_s: float = KINEMATIC_VISCOSITY_M2_S,
) -> float:
    """Compute a Darcy-Weisbach friction factor for EPANET-style calculations."""

    diameter_m = max(float(diameter_mm) / 1000.0, MIN_DIAMETER_M)
    q_m3s = abs(float(flow_lps)) / 1000.0
    if q_m3s <= 0:
        return 0.0
    area_m2 = np.pi * diameter_m**2 / 4.0
    reynolds = q_m3s / area_m2 * diameter_m / max(float(viscosity_m2_s), 1e-12)
    if reynolds <= 0:
        return 0.0
    if reynolds < 2000.0:
        return 64.0 / reynolds

    relative_roughness = max(float(roughness_mm), 0.0) / 1000.0 / diameter_m
    turbulent = 0.25 / (
        np.log10(relative_roughness / 3.7 + 5.74 / max(reynolds, 1.0) ** 0.9) ** 2
    )
    if reynolds >= 4000.0:
        return float(turbulent)
    laminar = 64.0 / reynolds
    ratio = (reynolds - 2000.0) / 2000.0
    return float(laminar + ratio * (turbulent - laminar))


def epanet_headloss_parts(
    flow_lps: float,
    length_m: float,
    diameter_mm: float,
    roughness: float,
    minor_loss_k: float = 0.0,
    *,
    formula: str | None = "H-W",
) -> HeadlossParts:
    """Return signed EPANET-style friction and minor head-loss components."""

    flow_m3s = float(flow_lps) / 1000.0
    sign = np.sign(flow_m3s)
    abs_flow = abs(flow_m3s)
    resistance, exponent, friction_factor = epanet_pipe_resistance(
        length_m,
        diameter_mm,
        roughness,
        formula=formula,
        flow_lps=flow_lps,
    )
    minor_resistance = epanet_minor_loss_resistance(diameter_mm, minor_loss_k)
    friction = sign * resistance * abs_flow**exponent
    minor = sign * minor_resistance * abs_flow**2
    return HeadlossParts(
        headloss_m=float(friction + minor),
        friction_headloss_m=float(friction),
        minor_headloss_m=float(minor),
        resistance=float(resistance),
        exponent=float(exponent),
        minor_resistance=float(minor_resistance),
        friction_factor=friction_factor,
    )


def epanet_headloss_m(
    flow_lps: float | pd.Series | np.ndarray,
    length_m: float | pd.Series | np.ndarray,
    diameter_mm: float | pd.Series | np.ndarray,
    roughness: float | pd.Series | np.ndarray,
    minor_loss_k: float | pd.Series | np.ndarray = 0.0,
    *,
    formula: str | None = "H-W",
) -> float | pd.Series | np.ndarray:
    """Compute signed EPANET-style pipe head loss in metres."""

    if np.isscalar(flow_lps):
        return epanet_headloss_parts(
            float(flow_lps),
            float(length_m),
            float(diameter_mm),
            float(roughness),
            float(minor_loss_k),
            formula=formula,
        ).headloss_m

    flow = np.asarray(flow_lps, dtype=float)
    length = np.asarray(length_m, dtype=float)
    diameter = np.asarray(diameter_mm, dtype=float)
    rough = np.asarray(roughness, dtype=float)
    minor = np.asarray(minor_loss_k, dtype=float)
    values = np.array(
        [
            epanet_headloss_parts(q, l, d, r, k, formula=formula).headloss_m
            for q, l, d, r, k in np.broadcast(flow, length, diameter, rough, minor)
        ]
    ).reshape(np.broadcast(flow, length, diameter, rough, minor).shape)
    if isinstance(flow_lps, pd.Series):
        return pd.Series(values, index=flow_lps.index)
    return values


def epanet_headloss_gradient_m_per_lps(
    flow_lps: float,
    length_m: float,
    diameter_mm: float,
    roughness: float,
    minor_loss_k: float = 0.0,
    *,
    formula: str | None = "H-W",
) -> float:
    """Return ``dh/dQ`` where ``Q`` is expressed in L/s."""

    flow_m3s = abs(float(flow_lps)) / 1000.0
    resistance, exponent, _friction_factor = epanet_pipe_resistance(
        length_m,
        diameter_mm,
        roughness,
        formula=formula,
        flow_lps=flow_lps,
    )
    minor_resistance = epanet_minor_loss_resistance(diameter_mm, minor_loss_k)
    gradient_m_per_m3s = (
        exponent * resistance * max(flow_m3s, 1e-12) ** (exponent - 1.0)
        + 2.0 * minor_resistance * flow_m3s
    )
    return float(max(gradient_m_per_m3s / 1000.0, 1e-12))


def hazen_williams_headloss_m(
    flow_lps: float | pd.Series | np.ndarray,
    length_m: float | pd.Series | np.ndarray,
    diameter_mm: float | pd.Series | np.ndarray,
    roughness_c: float | pd.Series | np.ndarray,
    minor_loss_k: float | pd.Series | np.ndarray = 0.0,
) -> float | pd.Series | np.ndarray:
    """Compatibility wrapper for EPANET's Hazen-Williams head-loss formula."""

    return epanet_headloss_m(
        flow_lps,
        length_m,
        diameter_mm,
        roughness_c,
        minor_loss_k,
        formula="H-W",
    )


def epanet_flow_from_headloss_lps(
    headloss_m: float,
    length_m: float,
    diameter_mm: float,
    roughness: float,
    minor_loss_k: float = 0.0,
    *,
    formula: str | None = "H-W",
) -> float:
    """Invert EPANET's pipe head-loss equation for one pipe by bisection."""

    target = float(headloss_m)
    if abs(target) < 1e-12:
        return 0.0
    sign = 1.0 if target >= 0 else -1.0
    target_abs = abs(target)
    formula_key = normalize_headloss_formula(formula)

    if formula_key in {"H-W", "C-M"}:
        resistance, exponent, _friction_factor = epanet_pipe_resistance(
            length_m,
            diameter_mm,
            roughness,
            formula=formula_key,
            flow_lps=1.0,
        )
        minor_resistance = epanet_minor_loss_resistance(diameter_mm, minor_loss_k)
        if minor_resistance <= 0:
            return sign * (target_abs / max(resistance, 1e-30)) ** (1.0 / exponent) * 1000.0
        q_m3s = (target_abs / max(resistance + minor_resistance, 1e-30)) ** (1.0 / max(exponent, 2.0))
        for _ in range(16):
            value = resistance * q_m3s**exponent + minor_resistance * q_m3s**2 - target_abs
            gradient = exponent * resistance * max(q_m3s, 1e-12) ** (exponent - 1.0) + 2.0 * minor_resistance * q_m3s
            q_m3s = max(q_m3s - value / max(gradient, 1e-30), 0.0)
        return sign * q_m3s * 1000.0

    low = 0.0
    high = 1.0
    while abs(epanet_headloss_m(sign * high, length_m, diameter_mm, roughness, minor_loss_k, formula=formula)) < target_abs:
        high *= 2.0
        if high > 1_000_000.0:
            break
    for _ in range(80):
        mid = (low + high) / 2.0
        value = abs(epanet_headloss_m(sign * mid, length_m, diameter_mm, roughness, minor_loss_k, formula=formula))
        if value < target_abs:
            low = mid
        else:
            high = mid
    return sign * (low + high) / 2.0


def add_headloss_columns(pipe_results: pd.DataFrame, *, formula: str | None = "H-W") -> pd.DataFrame:
    """Return a copy of pipe results with EPANET-style head-loss columns."""

    result = pipe_results.copy()
    result["headloss_m"] = epanet_headloss_m(
        result["flow_lps"],
        result["length_m"],
        result["diameter_mm"],
        result.get("adjusted_roughness_c", result.get("roughness_c", 100.0)),
        result.get("minor_loss_k", 0.0),
        formula=formula,
    )
    result["headloss_gradient_m_per_km"] = result["headloss_m"].abs() / result["length_m"].clip(lower=1.0) * 1000.0
    return result
