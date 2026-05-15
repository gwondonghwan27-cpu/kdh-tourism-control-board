import math

from aging_water_network.hydraulics.headloss import (
    darcy_weisbach_friction_factor,
    epanet_flow_from_headloss_lps,
    epanet_headloss_m,
    epanet_headloss_parts,
    epanet_pipe_resistance,
)


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
