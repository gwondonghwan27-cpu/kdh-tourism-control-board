"""Small typed records shared by the simulator, controller, and UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class PipeRecord:
    pipe_id: str
    from_node: str
    to_node: str
    length_m: float
    diameter_mm: float
    material: str
    install_year: int
    bend_count: int = 0
    valve_count: int = 0
    repair_count: int = 0
    leak_history_count: int = 0
    soil_ph: float = 7.0
    soil_resistivity_ohm_cm: float = 3000.0
    traffic_load_index: float = 0.0
    burst_history_count: int = 0


@dataclass(frozen=True)
class AgingScoreResult:
    pipe_id: str
    aging_score: float
    components: Dict[str, float]

    def to_row(self) -> Dict[str, float]:
        row = {"pipe_id": self.pipe_id, "aging_score": self.aging_score}
        row.update(self.components)
        return row


@dataclass(frozen=True)
class HydraulicPipeParams:
    pipe_id: str
    base_roughness_c: float
    adjusted_roughness_c: float
    minor_loss_k: float
    leak_probability: float
    burst_probability: float


@dataclass(frozen=True)
class PressureViolation:
    node_id: str
    pressure_head_m: float
    threshold_m: float = 15.0
    severity: str = "violation"


@dataclass(frozen=True)
class ControlRecommendation:
    action_id: str
    action_type: str
    target_id: Optional[str]
    description: str
    expected_effect: str
    score: float
    risks: List[str] = field(default_factory=list)
    affected_nodes: List[str] = field(default_factory=list)
    affected_pipes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

