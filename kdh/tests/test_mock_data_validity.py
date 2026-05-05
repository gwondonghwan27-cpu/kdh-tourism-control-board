from aging_water_network.data.mock_generator import SCENARIOS, build_mock_tables
from aging_water_network.data.validators import collect_validation_errors
from aging_water_network.hydraulics.simulator import compute_fallback_aging_scores, compute_pipe_hydraulic_params


def test_all_mock_scenarios_are_schema_valid():
    for scenario in SCENARIOS:
        tables = build_mock_tables(scenario=scenario)

        assert collect_validation_errors(tables) == []
        assert len(tables["nodes"]) >= 31
        assert len(tables["pipes"]) >= 1


def test_aging_params_are_bounded_and_roughness_decreases_with_age():
    tables = build_mock_tables(scenario="aging_headloss")
    aging = compute_fallback_aging_scores(tables["pipes"])
    params = compute_pipe_hydraulic_params(tables["pipes"], aging)

    assert aging["aging_score"].between(0.0, 1.0).all()
    assert params["adjusted_roughness_c"].between(45.0, 150.0).all()
    assert (params["adjusted_roughness_c"] <= params["base_roughness_c"]).all()
    assert params["leak_probability"].between(0.0, 0.6).all()
    assert params["burst_probability"].between(0.0, 0.4).all()
