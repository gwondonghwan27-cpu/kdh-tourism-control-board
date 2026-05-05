"""Project-wide constants and deterministic defaults."""

from __future__ import annotations

CURRENT_YEAR = 2026

MIN_PRESSURE_HEAD_M = 15.0
MARGINAL_PRESSURE_HEAD_M = 20.0
HIGH_PRESSURE_STRESS_M = 60.0

HEAD_LOSS_GRADIENT_WARNING = 0.03
HEAD_LOSS_GRADIENT_CRITICAL = 0.06

DEFAULT_AGING_WEIGHTS = {
    "age": 0.22,
    "material": 0.16,
    "repair": 0.10,
    "leak_history": 0.12,
    "geometry": 0.08,
    "soil": 0.14,
    "traffic": 0.08,
    "pressure_stress": 0.06,
    "topology": 0.04,
}

DESIGN_LIFE_BY_MATERIAL = {
    "cast_iron": 60,
    "steel": 50,
    "ductile_iron": 70,
    "PVC": 80,
    "HDPE": 80,
    "concrete": 60,
    "unknown": 50,
}

MATERIAL_RISK = {
    "cast_iron": 0.85,
    "steel": 0.80,
    "concrete": 0.60,
    "ductile_iron": 0.45,
    "PVC": 0.25,
    "HDPE": 0.20,
    "unknown": 0.55,
}

BASE_HW_C = {
    "cast_iron": 110.0,
    "steel": 120.0,
    "ductile_iron": 130.0,
    "PVC": 150.0,
    "HDPE": 150.0,
    "concrete": 120.0,
    "unknown": 120.0,
}

MAX_C_DEGRADATION = 0.35
BASE_LEAK_PROBABILITY = 0.005
LEAK_AGING_MULTIPLIER = 0.20
BASE_BURST_PROBABILITY = 0.001

DEFAULT_DATA_DIR = "data/mock"

