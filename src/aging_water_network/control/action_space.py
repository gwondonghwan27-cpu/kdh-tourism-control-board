"""Discrete operational actions considered by the rule-based controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import pandas as pd


@dataclass(frozen=True)
class ControlAction:
    """A candidate operation to evaluate against hydraulic constraints."""

    action_id: str
    action_type: str
    target_id: str | None
    description: str
    source_head_delta_m: float = 0.0
    valve_status_overrides: dict[str, str] = field(default_factory=dict)
    expected_effect: str = ""
    risks: tuple[str, ...] = ()

    def simulation_kwargs(self) -> dict[str, object]:
        return {
            "source_head_delta_m": self.source_head_delta_m,
            "valve_status_overrides": dict(self.valve_status_overrides),
        }


def _openable_valves(valves: pd.DataFrame) -> list[Mapping[str, object]]:
    if valves.empty or "status" not in valves.columns:
        return []
    closedish = valves["status"].astype(str).str.lower().isin({"closed", "partially_open"})
    return valves.loc[closedish].to_dict("records")


def _throttleable_valves(valves: pd.DataFrame) -> list[Mapping[str, object]]:
    if valves.empty or "status" not in valves.columns:
        return []
    openish = valves["status"].astype(str).str.lower().eq("open")
    if "valve_type" in valves.columns:
        controllable = (
            valves["valve_type"].astype(str).str.lower().isin({"prv", "control", "isolation"})
        )
        openish &= controllable
    return valves.loc[openish].to_dict("records")


def build_action_space(
    tables: Mapping[str, pd.DataFrame],
    include_noop: bool = True,
    source_head_steps_m: tuple[float, ...] = (-5.0, -2.5, 0.0, 2.5, 5.0, 7.5),
) -> list[ControlAction]:
    """Return deterministic candidate actions for pump/source and valve operations."""

    actions: list[ControlAction] = []
    if include_noop:
        actions.append(
            ControlAction(
                action_id="noop",
                action_type="no_action",
                target_id=None,
                description="Keep current source head and valve statuses.",
                expected_effect="Baseline hydraulic state for comparison.",
            )
        )

    for delta in source_head_steps_m:
        if delta == 0.0:
            continue
        label = "increase" if delta > 0 else "decrease"
        actions.append(
            ControlAction(
                action_id=f"source_head_{delta:+.1f}m",
                action_type="increase_pump_speed" if delta > 0 else "decrease_pump_speed",
                target_id="source",
                description=f"{label.title()} source or pump head by {abs(delta):.1f} m.",
                source_head_delta_m=float(delta),
                expected_effect=(
                    "Raise low-pressure nodes."
                    if delta > 0
                    else "Relieve pressure stress on aged pipes."
                ),
                risks=(
                    ("May increase overpressure stress on vulnerable pipes.",)
                    if delta > 0
                    else ("May create service-pressure violations at remote demand nodes.",)
                ),
            )
        )

    valves = tables.get("valves", pd.DataFrame())
    for valve in _openable_valves(valves):
        valve_id = str(valve["valve_id"])
        actions.append(
            ControlAction(
                action_id=f"open_{valve_id}",
                action_type="open_valve",
                target_id=valve_id,
                description=f"Open valve {valve_id} to reduce local head loss.",
                valve_status_overrides={valve_id: "open"},
                expected_effect="Improve conveyance and recover pressure downstream.",
                risks=("Could increase flow and pressure stress near aged downstream pipes.",),
            )
        )

    for valve in _throttleable_valves(valves):
        valve_id = str(valve["valve_id"])
        actions.append(
            ControlAction(
                action_id=f"partially_close_{valve_id}",
                action_type="partially_close_valve",
                target_id=valve_id,
                description=f"Partially close valve {valve_id} for pressure relief.",
                valve_status_overrides={valve_id: "partially_open"},
                expected_effect="Reduce pressure stress in nearby aged pipe segments.",
                risks=("May lower downstream pressure below the service threshold.",),
            )
        )

    for pipe in _inspection_targets(tables.get("pipes", pd.DataFrame())):
        pipe_id = str(pipe["pipe_id"])
        actions.append(
            ControlAction(
                action_id=f"inspect_{pipe_id}",
                action_type="dispatch_inspection",
                target_id=pipe_id,
                description=f"Dispatch inspection to vulnerable pipe {pipe_id}.",
                expected_effect="Improves leak/roughness diagnosis without changing hydraulic controls.",
                risks=("Does not immediately recover pressure head.",),
            )
        )

    return actions


def _inspection_targets(pipes: pd.DataFrame, limit: int = 3) -> list[Mapping[str, object]]:
    if pipes.empty:
        return []
    frame = pipes.copy()
    age = (2026 - pd.to_numeric(frame["install_year"], errors="coerce").fillna(2026)).clip(0, 120) / 80.0
    repairs = pd.to_numeric(frame.get("repair_count", 0), errors="coerce").fillna(0).clip(0, 5) / 5.0
    leaks = pd.to_numeric(frame.get("leak_history_count", 0), errors="coerce").fillna(0).clip(0, 3) / 3.0
    material = frame.get("material", pd.Series("unknown", index=frame.index)).astype(str).str.lower()
    material_risk = material.map(
        {"cast_iron": 0.85, "steel": 0.80, "concrete": 0.60, "ductile_iron": 0.45, "pvc": 0.25, "hdpe": 0.20}
    ).fillna(0.55)
    frame["inspection_score"] = (0.35 * age + 0.25 * material_risk + 0.20 * repairs + 0.20 * leaks).clip(0, 1)
    return frame.sort_values("inspection_score", ascending=False).head(limit).to_dict("records")
