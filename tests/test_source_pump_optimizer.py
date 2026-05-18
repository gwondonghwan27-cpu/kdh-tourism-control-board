from aging_water_network.data.mock_generator import build_mock_tables
from aging_water_network.hydraulics.source_pump_optimizer import (
    clear_source_pump_optimizer_cache,
    predict_source_pump_operation,
)


def test_source_pump_prediction_recovers_low_pressure_and_reports_flows():
    clear_source_pump_optimizer_cache()
    tables = build_mock_tables(scenario="aging_headloss")

    prediction = predict_source_pump_operation(tables)

    assert prediction["recommended_boost_m"] >= 0
    assert prediction["predicted_min_pressure_m"] >= 15.0
    assert prediction["low_pressure_nodes_before"]
    assert not prediction["low_pressure_nodes_after"]
    assert prediction["sources"]
    assert prediction["pumps"]
    assert prediction["total_source_outflow_lps"] >= 0
    assert prediction["total_estimated_pump_kw"] >= 0
    assert prediction["total_estimated_energy_cost_per_hour"] >= 0
    assert prediction["control_plan"]
    assert any(item["recommended_boost_m"] > 0 for item in prediction["control_plan"])
    assert all("flow_contribution_percent" in item for item in prediction["control_plan"])
    assert prediction["hydraulic_simulation_count"] > 0
    assert prediction["critical_junction_count"] > 0
    assert prediction["active_set_rounds"] >= 1
    assert prediction["critical_junctions"]
    assert "sdi_active_set" in prediction["optimization_method"]


def test_source_pump_prediction_cache_and_asset_status_are_explicit():
    clear_source_pump_optimizer_cache()
    tables = build_mock_tables(scenario="aging_headloss")

    first = predict_source_pump_operation(tables)
    second = predict_source_pump_operation(tables)

    assert not first["cache_hit"]
    assert second["cache_hit"]
    assert all("optimization_status" in item for item in first["sources"])
    assert all("recommended_boost_m" in item for item in first["pumps"])
    assert all("efficiency_percent" in item for item in first["pumps"])
    assert all("operating_flow_lps" in item for item in first["pumps"])
