import math

import pandas as pd

from aging_water_network.hydraulics.energy import (
    energy_options_from_tables,
    estimate_energy_cost,
    estimate_pump_kw,
    pump_efficiency_at_flow,
)


def test_energy_options_and_fixed_efficiency_are_normalized():
    tables = {
        "energy_options": pd.DataFrame(
            [
                {
                    "global_efficiency_percent": 70,
                    "global_price_per_kwh": 0.18,
                    "demand_charge": 2.5,
                }
            ]
        )
    }

    options = energy_options_from_tables(tables)

    assert options["global_efficiency_percent"] == 70
    assert options["global_price_per_kwh"] == 0.18
    assert pump_efficiency_at_flow({}, 12.0, options) == 0.70


def test_efficiency_curve_interpolates_by_flow():
    pump = {
        "efficiency_curve_points": [
            {"flow_lps": 0, "efficiency_percent": 60},
            {"flow_lps": 20, "efficiency_percent": 80},
        ]
    }

    assert math.isclose(pump_efficiency_at_flow(pump, 10.0), 0.70)


def test_pump_power_and_cost_estimates_are_positive():
    kw = estimate_pump_kw(flow_lps=20.0, head_m=35.0, efficiency=0.7)
    cost = estimate_energy_cost(kwh=kw, price_per_kwh=0.2)

    assert kw > 0
    assert math.isclose(cost, kw * 0.2)
