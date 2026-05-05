"""Hydraulic head-loss formulas used by WNTR and fallback simulations."""

from __future__ import annotations

import numpy as np
import pandas as pd


def hazen_williams_headloss_m(
    flow_lps: float | pd.Series | np.ndarray,
    length_m: float | pd.Series | np.ndarray,
    diameter_mm: float | pd.Series | np.ndarray,
    roughness_c: float | pd.Series | np.ndarray,
    minor_loss_k: float | pd.Series | np.ndarray = 0.0,
) -> float | pd.Series | np.ndarray:
    """Compute Hazen-Williams plus minor-loss head loss in metres.

    The formula uses SI units with flow converted from L/s to m3/s and
    diameter converted from mm to m. Negative flows preserve direction.
    """

    flow = np.asarray(flow_lps, dtype=float)
    sign = np.sign(flow)
    q_m3s = np.abs(flow) / 1000.0
    length = np.asarray(length_m, dtype=float)
    diameter_m = np.maximum(np.asarray(diameter_mm, dtype=float) / 1000.0, 1e-6)
    c_value = np.maximum(np.asarray(roughness_c, dtype=float), 1.0)
    minor_k = np.maximum(np.asarray(minor_loss_k, dtype=float), 0.0)

    friction = 10.67 * length * np.power(q_m3s, 1.852) / (np.power(c_value, 1.852) * np.power(diameter_m, 4.871))
    velocity = q_m3s / (np.pi * np.power(diameter_m, 2) / 4.0)
    minor = minor_k * np.power(velocity, 2) / (2.0 * 9.80665)
    result = sign * (friction + minor)

    if np.isscalar(flow_lps):
        return float(result)
    if isinstance(flow_lps, pd.Series):
        return pd.Series(result, index=flow_lps.index)
    return result


def add_headloss_columns(pipe_results: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of pipe results with computed head-loss columns."""

    result = pipe_results.copy()
    result["headloss_m"] = hazen_williams_headloss_m(
        result["flow_lps"],
        result["length_m"],
        result["diameter_mm"],
        result.get("adjusted_roughness_c", result.get("roughness_c", 100.0)),
        result.get("minor_loss_k", 0.0),
    )
    result["headloss_gradient_m_per_km"] = result["headloss_m"].abs() / result["length_m"].clip(lower=1.0) * 1000.0
    return result
