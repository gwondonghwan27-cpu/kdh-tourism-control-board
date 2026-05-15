import math

import pandas as pd

from aging_water_network.hydraulics.headloss import (
    darcy_weisbach_friction_factor,
    epanet_flow_from_headloss_lps,
    epanet_headloss_m,
    epanet_headloss_parts,
    epanet_pipe_resistance,
)
from aging_water_network.hydraulics.simulator import _build_hydraulic_graph, _interpolate_pump_curve_head


def test_hazen_williams_matches_epanet_si_coefficient():
    flow_lps = 10.0
    length_m = 1000.0
    diameter_mm = 300.0
    roughness_c = 130.0

    expected = 10.67 * length_m / (roughness_c**1.852 * (diameter_mm / 1000) ** 4.871)
    expected *= (flow_lps / 1000) ** 1.852

    actual = epanet_headloss_m(flow_lps, length_m, diameter_mm, roughness_c, formula="H-W")

    assert math.isclose(actual, expected, rel_tol=1e-12)


def test_minor_loss_adds_velocity_head_component():
    base = epanet_headloss_parts(20.0, 500.0, 250.0, 120.0, 0.0)
    with_minor = epanet_headloss_parts(20.0, 500.0, 250.0, 120.0, 2.0)

    assert with_minor.headloss_m > base.headloss_m
    assert with_minor.minor_headloss_m > 0


def test_inverse_headloss_recovers_flow():
    headloss = epanet_headloss_m(14.5, 800.0, 200.0, 110.0, 0.4)
    flow = epanet_flow_from_headloss_lps(headloss, 800.0, 200.0, 110.0, 0.4)

    assert math.isclose(flow, 14.5, rel_tol=1e-8)


def test_darcy_and_manning_resistance_are_positive():
    friction = darcy_weisbach_friction_factor(12.0, 200.0, 0.1)
    dw_resistance, dw_exponent, _ = epanet_pipe_resistance(1000.0, 200.0, 0.1, formula="D-W", flow_lps=12.0)
    cm_resistance, cm_exponent, _ = epanet_pipe_resistance(1000.0, 200.0, 0.013, formula="C-M")

    assert friction > 0
    assert dw_resistance > 0
    assert dw_exponent == 2.0
    assert cm_resistance > 0
    assert cm_exponent == 2.0


def test_pump_curve_uses_forward_flow_and_clamps_reverse_flow_to_shutoff():
    curve = [(0.0, 50.0), (20.0, 40.0), (40.0, 25.0)]

    assert math.isclose(_interpolate_pump_curve_head(20.0, curve, 1.0), 40.0)
    assert math.isclose(_interpolate_pump_curve_head(-20.0, curve, 1.0), 50.0)


def test_pipe_status_closed_is_reflected_in_hydraulic_graph_weight():
    params = pd.DataFrame([{"pipe_id": "P1", "adjusted_roughness_c": 120.0, "minor_loss_k": 0.0}])
    open_pipe = pd.DataFrame(
        [{"pipe_id": "P1", "from_node": "A", "to_node": "B", "length_m": 100.0, "diameter_mm": 200.0, "roughness_c": 120.0, "status": "OPEN"}]
    )
    closed_pipe = open_pipe.assign(status="CLOSED")

    open_weight = _build_hydraulic_graph(open_pipe, params)["A"]["B"]["weight"]
    closed_weight = _build_hydraulic_graph(closed_pipe, params)["A"]["B"]["weight"]

    assert closed_weight > open_weight * 100_000
