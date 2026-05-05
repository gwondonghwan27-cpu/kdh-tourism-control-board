from aging_water_network.data.mock_generator import build_mock_tables
from aging_water_network.hydraulics.pressure_checks import detect_pressure_violations
from aging_water_network.hydraulics.simulator import run_hydraulic_simulation


def test_fallback_simulation_reports_pressure_violations_for_aging_scenario():
    tables = build_mock_tables(scenario="aging_headloss")

    result = run_hydraulic_simulation(tables=tables, prefer_wntr=False)

    node_results = result["node_results"]
    pipe_results = result["pipe_results"]
    violations = result["pressure_violations"]

    assert not node_results.empty
    assert not pipe_results.empty
    assert {"node_id", "pressure_head_m", "is_pressure_compliant"}.issubset(node_results.columns)
    assert {"pipe_id", "flow_lps", "headloss_m", "adjusted_roughness_c", "aging_score"}.issubset(pipe_results.columns)
    assert not violations.empty
    assert (violations["pressure_head_m"] < 15.0).all()


def test_pressure_violation_helper_can_include_warning_band():
    tables = build_mock_tables(scenario="normal")
    result = run_hydraulic_simulation(tables=tables, min_pressure_head_m=20.0, prefer_wntr=False)

    violations = detect_pressure_violations(result["node_results"], threshold_m=20.0, include_warnings=True)

    assert {"critical", "violation", "warning"}.issuperset(set(violations["severity"]))
    assert (violations["pressure_margin_m"] < 2.0).all()
