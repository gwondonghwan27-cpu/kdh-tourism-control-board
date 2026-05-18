"""Pump energy and cost helpers for lightweight operating estimates."""

from __future__ import annotations

import json
from collections.abc import Mapping as MappingABC
from typing import Any, Mapping

import pandas as pd


WATER_DENSITY_KG_M3 = 1000.0
GRAVITY_M_S2 = 9.80665
DEFAULT_EFFICIENCY_PERCENT = 65.0
DEFAULT_PRICE_PER_KWH = 0.0


def energy_options_from_tables(tables: Mapping[str, pd.DataFrame]) -> dict[str, float]:
    """Return normalized global EPANET [ENERGY] options."""

    frame = tables.get("energy_options", pd.DataFrame())
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {
            "global_efficiency_percent": DEFAULT_EFFICIENCY_PERCENT,
            "global_price_per_kwh": DEFAULT_PRICE_PER_KWH,
            "demand_charge": 0.0,
        }
    row = frame.iloc[0].to_dict()
    return {
        "global_efficiency_percent": _positive_float(
            row.get("global_efficiency_percent"),
            DEFAULT_EFFICIENCY_PERCENT,
        ),
        "global_price_per_kwh": _positive_float(
            row.get("global_price_per_kwh"),
            DEFAULT_PRICE_PER_KWH,
        ),
        "demand_charge": _positive_float(row.get("demand_charge"), 0.0),
    }


def pump_energy_lookup(tables: Mapping[str, pd.DataFrame]) -> dict[str, dict[str, Any]]:
    """Return pump-specific [ENERGY] settings keyed by pump id."""

    frame = tables.get("pump_energy", pd.DataFrame())
    if not isinstance(frame, pd.DataFrame) or frame.empty or "pump_id" not in frame.columns:
        return {}
    return {str(row.get("pump_id", "")): row for row in frame.to_dict("records")}


def merge_pump_energy(
    pump: Mapping[str, Any],
    tables: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    """Merge pump row values with optional pump_energy table values."""

    pump_id = str(pump.get("pump_id", ""))
    merged = dict(pump)
    merged.update({key: value for key, value in pump_energy_lookup(tables).get(pump_id, {}).items() if value not in ("", None)})
    return merged


def pump_efficiency_at_flow(
    pump: Mapping[str, Any],
    flow_lps: float,
    energy_options: Mapping[str, float] | None = None,
) -> float:
    """Return pump efficiency as a fraction for the current operating flow."""

    options = dict(energy_options or {})
    default_percent = _positive_float(
        options.get("global_efficiency_percent"),
        DEFAULT_EFFICIENCY_PERCENT,
    )
    curve_points = _efficiency_curve_points(pump)
    if curve_points:
        efficiency_percent = _interpolate_curve_value(max(float(flow_lps), 0.0), curve_points)
    else:
        efficiency_percent = _positive_float(
            pump.get("efficiency_percent"),
            default_percent,
        )
    return max(min(float(efficiency_percent) / 100.0, 1.0), 0.01)


def pump_energy_price(
    pump: Mapping[str, Any],
    energy_options: Mapping[str, float] | None = None,
) -> float:
    """Return pump-specific or global unit energy price."""

    options = dict(energy_options or {})
    return _positive_float(
        pump.get("energy_price_per_kwh"),
        _positive_float(options.get("global_price_per_kwh"), DEFAULT_PRICE_PER_KWH),
    )


def estimate_pump_kw(flow_lps: float, head_m: float, efficiency: float) -> float:
    """Estimate electrical kW from flow, pump head, and efficiency."""

    flow_m3s = max(abs(float(flow_lps)), 0.0) / 1000.0
    head = max(float(head_m), 0.0)
    eff = max(float(efficiency), 0.01)
    return WATER_DENSITY_KG_M3 * GRAVITY_M_S2 * flow_m3s * head / eff / 1000.0


def estimate_energy_cost(
    kwh: float,
    price_per_kwh: float,
    demand_charge: float = 0.0,
    peak_kw: float = 0.0,
) -> float:
    """Estimate energy cost for one operating period."""

    return max(float(kwh), 0.0) * max(float(price_per_kwh), 0.0) + max(float(demand_charge), 0.0) * max(float(peak_kw), 0.0)


def _efficiency_curve_points(pump: Mapping[str, Any]) -> list[tuple[float, float]]:
    raw_points = pump.get("efficiency_curve_points", [])
    if isinstance(raw_points, str):
        try:
            raw_points = json.loads(raw_points)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_points, list):
        return []
    points: list[tuple[float, float]] = []
    for point in raw_points:
        if not isinstance(point, MappingABC):
            continue
        flow = pd.to_numeric(point.get("flow_lps"), errors="coerce")
        efficiency = pd.to_numeric(point.get("efficiency_percent"), errors="coerce")
        if pd.notna(flow) and pd.notna(efficiency):
            points.append((float(flow), float(efficiency)))
    return sorted(points)


def _interpolate_curve_value(x_value: float, points: list[tuple[float, float]]) -> float:
    if len(points) == 1 or x_value <= points[0][0]:
        return points[0][1]
    for (x_a, y_a), (x_b, y_b) in zip(points, points[1:]):
        if x_value <= x_b:
            ratio = (x_value - x_a) / max(x_b - x_a, 1e-9)
            return y_a + ratio * (y_b - y_a)
    return points[-1][1]


def _positive_float(value: Any, fallback: float) -> float:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or float(number) < 0:
        return float(fallback)
    return float(number)
