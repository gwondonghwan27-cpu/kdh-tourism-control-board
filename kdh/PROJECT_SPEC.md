# Aging-Aware Hydraulic Digital Twin

## 노후도 반영 상수도 관망 수두 제어 시뮬레이터

This repository implements a proof-of-concept system for simulating and controlling an aging water distribution network.  
The system models how pipe aging, topology, valve operation, hydraulic stress, and environmental factors affect hydraulic roughness, leakage risk, head loss, and pressure-head stability.

The project goal is not to build a superficial dashboard.  
The goal is to build a physically grounded, extensible, testable local simulator that demonstrates how an aging-aware digital twin can maintain minimum service pressure while reducing stress on vulnerable pipe segments.

---

# 1. Core Objective

Build a local repository that can:

1. Generate or load a mock water distribution network.
2. Assign aging-related metadata to pipes, valves, pumps, and nodes.
3. Compute an aging score for each pipe.
4. Convert the aging score into hydraulic parameters:
   - reduced Hazen-Williams C value or increased roughness,
   - increased minor loss coefficient,
   - elevated leak probability,
   - elevated burst risk,
   - pressure-stress sensitivity.
5. Run hydraulic simulation using EPANET/WNTR-compatible logic.
6. Detect nodes where pressure head falls below the target threshold.
7. Recommend operational actions:
   - pump adjustment,
   - valve opening/closing,
   - pressure zone modification,
   - vulnerable pipe stress relief,
   - leak investigation priority.
8. Visualize:
   - pipe aging risk,
   - pressure head distribution,
   - head loss gradient,
   - vulnerable segments,
   - recommended control actions.
9. Provide reproducible mock data and unit tests.

The minimum service constraint is:

> Every demand node should maintain pressure head ≥ 15 m under normal service conditions.

The system should also avoid excessive pressure in highly aged pipes, because over-pressurization can increase leakage and burst risk.

---

# 2. Design Philosophy

## 2.1 Physics First, AI Second

This system must not be a vague machine-learning demo.

The correct architecture is:

> hydraulic model → residual/anomaly analysis → aging-aware risk model → control recommendation

AI or ML can be added later, but the first version must be physically interpretable.

The repository should therefore prioritize:

- explicit hydraulic assumptions,
- transparent formulas,
- deterministic mock-data generation,
- reproducible simulation results,
- clear separation between slow asset degradation and fast operational control.

## 2.2 Separate Slow Aging Loop and Fast Control Loop

Pipe aging is not updated every second.  
Aging is a slow state variable that changes over months or years.

Pressure, flow, pump state, and valve state are fast operational variables that may change minute by minute.

Therefore the system must have two loops:

### Slow loop: Asset condition update

Inputs:

- installation year,
- material,
- repair history,
- leak history,
- soil corrosivity,
- traffic load,
- valve operation frequency,
- pressure transient exposure,
- topology/criticality.

Outputs:

- pipe aging score,
- hydraulic roughness modifier,
- leak prior,
- burst prior,
- pipe vulnerability score.

### Fast loop: Hydraulic operation and control

Inputs:

- current demand,
- tank/reservoir level,
- pump status,
- valve status,
- pressure sensor readings,
- flow sensor readings,
- updated pipe parameters from slow loop.

Outputs:

- pressure head at nodes,
- flow in pipes,
- head loss by pipe,
- low-pressure alarms,
- high-pressure stress alarms,
- recommended control actions.

Do not collapse these two loops into one black-box model.

## 2.3 Interpretable Before Sophisticated

The first version should use rule-based and formula-based scoring, not a deep-learning model.

Machine learning can be introduced later only after:

- data schema is stable,
- simulation output is validated,
- baseline rules are implemented,
- tests exist,
- visualizations are meaningful.

## 2.4 Mock Data Is Acceptable, But Must Be Honest

This project uses mock data because real GIS/SCADA/sensor data is unavailable.

Therefore, never claim that this system predicts real pipe failure.  
The correct claim is:

> This is a proof-of-concept simulator showing how aging-related pipe metadata can be coupled to hydraulic simulation and control logic.

---

# 3. Core Engineering Requirements

## 3.1 Python Version

Use:

- Python 3.11 or 3.12

Preferred libraries:

- `pandas`
- `numpy`
- `networkx`
- `matplotlib`
- `plotly`
- `streamlit`
- `wntr`
- `pydantic`
- `pytest`

Optional later:

- `scikit-learn`
- `xgboost`
- `geopandas`
- `shapely`
- `folium`
- `fastapi`

## 3.2 Repository Structure

Implement the repository with this structure:

~~~text
aging-water-network/
  README.md
  PROJECT_SPEC.md
  pyproject.toml
  requirements.txt

  data/
    mock/
      nodes.csv
      pipes.csv
      valves.csv
      pumps.csv
      reservoirs.csv
      tanks.csv
      sensors.csv
      sensor_timeseries.csv
      demand_patterns.csv

  src/
    aging_water_network/
      __init__.py

      config.py
      schemas.py

      data/
        __init__.py
        mock_generator.py
        loaders.py
        validators.py

      aging/
        __init__.py
        scoring.py
        roughness.py
        risk.py

      hydraulics/
        __init__.py
        epanet_builder.py
        simulator.py
        headloss.py
        pressure_checks.py

      control/
        __init__.py
        controller.py
        action_space.py
        evaluator.py

      anomaly/
        __init__.py
        residuals.py
        leak_suspect.py

      topology/
        __init__.py
        graph_features.py
        criticality.py

      visualization/
        __init__.py
        network_plot.py
        pressure_plot.py
        risk_plot.py

  app/
    streamlit_app.py

  notebooks/
    01_generate_mock_data.ipynb
    02_aging_score_demo.ipynb
    03_hydraulic_simulation_demo.ipynb
    04_control_recommendation_demo.ipynb

  tests/
    test_aging_score.py
    test_roughness_mapping.py
    test_pressure_constraints.py
    test_mock_data_validity.py
    test_control_recommendations.py
~~~

---

# 4. Data Model

## 4.1 nodes.csv

Required columns:

~~~csv
node_id,x,y,elevation_m,base_demand_lps,node_type,dma_id
J1,0,0,32.0,2.4,junction,DMA_A
J2,100,0,31.2,1.8,junction,DMA_A
J3,200,40,29.5,2.2,junction,DMA_A
~~~

Column definitions:

- `node_id`: unique node identifier.
- `x`, `y`: local coordinate system for plotting.
- `elevation_m`: ground elevation.
- `base_demand_lps`: base water demand in liters per second.
- `node_type`: `junction`, `reservoir`, `tank`.
- `dma_id`: district metered area identifier.

## 4.2 pipes.csv

Required columns:

~~~csv
pipe_id,from_node,to_node,length_m,diameter_mm,material,install_year,bend_count,valve_count,repair_count,leak_history_count,soil_ph,soil_resistivity_ohm_cm,traffic_load_index,burst_history_count
P1,J1,J2,320,300,cast_iron,1988,2,1,3,1,6.1,1200,0.7,0
P2,J2,J3,180,250,ductile_iron,2005,1,0,0,0,7.0,2500,0.3,0
P3,J3,J4,260,200,PVC,2016,0,1,0,0,6.8,3100,0.2,0
~~~

Column definitions:

- `pipe_id`: unique pipe identifier.
- `from_node`, `to_node`: graph endpoints.
- `length_m`: pipe length.
- `diameter_mm`: pipe diameter.
- `material`: pipe material.
- `install_year`: year of installation.
- `bend_count`: number of bends or major directional changes.
- `valve_count`: number of valves associated with the pipe segment.
- `repair_count`: number of recorded repairs.
- `leak_history_count`: number of historical leak events.
- `soil_ph`: approximate soil pH.
- `soil_resistivity_ohm_cm`: soil resistivity. Lower values imply higher corrosion risk.
- `traffic_load_index`: normalized traffic/external loading index from 0 to 1.
- `burst_history_count`: number of previous burst events.

## 4.3 valves.csv

Required columns:

~~~csv
valve_id,pipe_id,valve_type,status,operation_count_last_year,minor_loss_k
V1,P1,isolation,open,12,0.2
V2,P4,PRV,open,350,1.5
~~~

Column definitions:

- `valve_type`: `isolation`, `PRV`, `check`, `control`.
- `status`: `open`, `closed`, `partially_open`.
- `operation_count_last_year`: number of operations in the last year.
- `minor_loss_k`: local loss coefficient.

## 4.4 sensors.csv

Required columns:

~~~csv
sensor_id,node_or_pipe_id,sensor_type,location_type,noise_std,last_calibrated_date
S1,J3,pressure,node,0.25,2026-01-01
S2,P4,flow,pipe,0.10,2026-01-01
~~~

Sensor types:

- `pressure`
- `flow`
- `tank_level`
- `valve_status`
- `pump_status`
- `water_quality`

## 4.5 sensor_timeseries.csv

Required columns:

~~~csv
timestamp,sensor_id,value
2026-01-01 00:00:00,S1,24.3
2026-01-01 00:05:00,S1,24.1
2026-01-01 00:10:00,S1,22.8
~~~

Pressure sensor values should be represented as pressure head in meters if possible.

---

# 5. Aging Model

## 5.1 Pipe Aging Score

Implement a deterministic pipe aging score from 0 to 1.

- `0.0`: excellent condition
- `0.5`: moderate aging
- `1.0`: severe aging

The scoring model must be modular and explainable.

Recommended components:

~~~text
aging_score =
    w_age              * age_component
  + w_material         * material_component
  + w_repair           * repair_component
  + w_leak_history     * leak_history_component
  + w_geometry         * geometry_component
  + w_soil             * soil_corrosion_component
  + w_traffic          * traffic_load_component
  + w_pressure_stress  * pressure_stress_component
  + w_topology         * topology_component
~~~

Weights must sum to 1.

Initial default weights:

~~~python
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
~~~

## 5.2 Component Definitions

### Age component

~~~text
age_years = current_year - install_year
age_component = min(age_years / design_life_years, 1.0)
~~~

Default design life:

~~~python
DESIGN_LIFE_BY_MATERIAL = {
    "cast_iron": 60,
    "steel": 50,
    "ductile_iron": 70,
    "PVC": 80,
    "HDPE": 80,
    "concrete": 60,
    "unknown": 50,
}
~~~

### Material component

~~~python
MATERIAL_RISK = {
    "cast_iron": 0.85,
    "steel": 0.80,
    "concrete": 0.60,
    "ductile_iron": 0.45,
    "PVC": 0.25,
    "HDPE": 0.20,
    "unknown": 0.55,
}
~~~

### Repair component

~~~text
repair_component = min(repair_count / 5, 1.0)
~~~

### Leak history component

~~~text
leak_history_component = min(leak_history_count / 3, 1.0)
~~~

### Geometry component

Bends, fittings, valves, and local loss sources increase hydraulic complexity.

~~~text
geometry_component = min((bend_count + valve_count) / 8, 1.0)
~~~

Later, replace this with explicit minor-loss coefficient aggregation.

### Soil corrosion component

Soil corrosion risk should consider both pH and resistivity.

Initial simple rule:

~~~text
if soil_ph < 6.0:
    ph_risk = 1.0
elif soil_ph < 6.5:
    ph_risk = 0.75
elif soil_ph < 7.5:
    ph_risk = 0.35
else:
    ph_risk = 0.45
~~~

Resistivity risk:

~~~text
if resistivity < 1000:
    resistivity_risk = 1.0
elif resistivity < 2000:
    resistivity_risk = 0.75
elif resistivity < 5000:
    resistivity_risk = 0.40
else:
    resistivity_risk = 0.20
~~~

Then:

~~~text
soil_component = 0.5 * ph_risk + 0.5 * resistivity_risk
~~~

### Traffic component

~~~text
traffic_component = clip(traffic_load_index, 0, 1)
~~~

### Pressure stress component

This component should be computed after hydraulic simulation.

Recommended features:

- mean pressure head,
- max pressure head,
- pressure variability,
- transient event count,
- pump start/stop exposure,
- valve operation exposure.

Initial mock version:

~~~text
pressure_stress_component =
    clip((mean_pressure_head_m - 30) / 40, 0, 1) * 0.5
  + clip(pressure_head_std_m / 10, 0, 1) * 0.5
~~~

### Topology component

Use graph-based features.

Potential features:

- betweenness centrality,
- bridge edge status,
- loop redundancy,
- number of downstream demand nodes,
- DMA criticality,
- lack of alternative path.

Initial version:

~~~text
topology_component = normalized_edge_betweenness_centrality
~~~

Interpretation:

A highly central pipe may not be more physically aged, but it is more critical.  
Therefore this feature should eventually be separated into `criticality_score`.

For MVP, it may be included as a small component of the risk score.

---

# 6. Hydraulic Parameter Mapping

The aging score should modify hydraulic behavior.

## 6.1 Hazen-Williams Roughness C

Base values:

~~~python
BASE_HW_C = {
    "cast_iron": 110,
    "steel": 120,
    "ductile_iron": 130,
    "PVC": 150,
    "HDPE": 150,
    "concrete": 120,
    "unknown": 120,
}
~~~

Aging-adjusted C:

~~~text
C_adjusted = C_base * (1 - max_c_degradation * aging_score)
~~~

Default:

~~~python
max_c_degradation = 0.35
~~~

So if:

- base C = 110
- aging_score = 0.8
- max degradation = 0.35

Then:

~~~text
C_adjusted = 110 * (1 - 0.35 * 0.8)
           = 110 * 0.72
           = 79.2
~~~

This means a severely aged pipe has larger friction loss.

## 6.2 Minor Loss Coefficient

Aging, bends, fittings, and partially closed valves increase local losses.

~~~text
K_total = K_base + K_bends + K_valves + K_aging
~~~

Initial mock formula:

~~~text
K_bends = 0.2 * bend_count
K_valves = sum(valve_minor_loss_k)
K_aging = 1.5 * aging_score
~~~

## 6.3 Leak Probability

~~~text
leak_probability = base_leak_probability + aging_multiplier * aging_score
~~~

Default:

~~~python
base_leak_probability = 0.005
aging_multiplier = 0.20
~~~

Clip to `[0, 1]`.

## 6.4 Burst Probability

Burst probability should be more sensitive to severe aging and pressure stress.

~~~text
burst_probability =
    base_burst_probability
  + 0.10 * aging_score^2
  + 0.08 * pressure_stress_component
  + 0.05 * leak_history_component
~~~

Default:

~~~python
base_burst_probability = 0.001
~~~

This is not a calibrated real-world probability.  
It is a risk index for simulation and prioritization.

---

# 7. Hydraulic Simulation

## 7.1 Preferred Simulation Engine

Use `wntr` if available.

The repository should be able to:

1. Construct a `WaterNetworkModel` from mock CSV files.
2. Assign junction elevations and demands.
3. Add reservoirs/tanks.
4. Add pipes with length, diameter, and roughness.
5. Add valves and pumps if supported.
6. Run simulation.
7. Extract:
   - node pressure,
   - node head,
   - pipe flow,
   - link velocity,
   - head loss,
   - demand satisfaction.

## 7.2 Pressure Head Constraint

The primary constraint:

~~~python
MIN_PRESSURE_HEAD_M = 15.0
~~~

For every demand node:

~~~text
pressure_head_m >= 15.0
~~~

Pressure status labels:

~~~text
pressure_head < 10 m      → critical
10 m ≤ pressure_head < 15 m → violation
15 m ≤ pressure_head < 20 m → marginal
20 m ≤ pressure_head < 60 m → normal
pressure_head ≥ 60 m       → high-pressure stress
~~~

## 7.3 Head Loss Gradient

For each pipe:

~~~text
head_loss_gradient = abs(head_from_node - head_to_node) / length_m
~~~

Flag abnormal gradient if:

~~~text
head_loss_gradient > threshold
~~~

Initial threshold:

~~~python
HEAD_LOSS_GRADIENT_WARNING = 0.03  # m/m
HEAD_LOSS_GRADIENT_CRITICAL = 0.06 # m/m
~~~

These thresholds are mock defaults and should be configurable.

## 7.4 Residual-Based Anomaly Detection

If mock sensor data exists:

~~~text
pressure_residual = observed_pressure_head - simulated_pressure_head
flow_residual = observed_flow - simulated_flow
~~~

Flag anomalies:

~~~text
abs(pressure_residual) > 3 * sensor_noise_std
abs(flow_residual) > 3 * sensor_noise_std
~~~

Potential classifications:

- `sensor_fault`
- `leak_suspected`
- `valve_partially_closed`
- `unexpected_demand_spike`
- `pump_operation_mismatch`
- `model_calibration_error`

---

# 8. Control Recommendation Logic

## 8.1 Control Objective

The controller should recommend actions that satisfy:

1. Keep all demand nodes above 15 m pressure head.
2. Avoid excessive pressure in highly aged pipes.
3. Reduce stress on pipes with high aging score.
4. Preserve supply continuity.
5. Minimize unnecessary valve and pump operations.
6. Prefer interpretable, safe recommendations.

## 8.2 Action Space

Define possible actions:

~~~python
ActionType = Literal[
    "increase_pump_speed",
    "decrease_pump_speed",
    "open_valve",
    "close_valve",
    "partially_close_valve",
    "adjust_prv_setpoint",
    "isolate_suspected_leak",
    "reroute_flow",
    "dispatch_inspection",
    "no_action"
]
~~~

Each action should include:

~~~python
class ControlAction(BaseModel):
    action_id: str
    action_type: str
    target_id: str
    description: str
    expected_min_pressure_head_m: float | None
    expected_max_pressure_head_m: float | None
    affected_nodes: list[str]
    affected_pipes: list[str]
    risk_notes: list[str]
    priority: int
~~~

## 8.3 Evaluation of Candidate Actions

For each candidate action:

1. Apply action to copied network model.
2. Re-run hydraulic simulation.
3. Compute:
   - minimum pressure head,
   - number of pressure violations,
   - maximum pressure near aged pipes,
   - total estimated energy penalty,
   - total estimated valve operation penalty,
   - leak-risk-weighted pressure exposure.
4. Rank actions by score.

Recommended scoring:

~~~text
action_score =
    + 1000 * pressure_constraint_satisfied
    - 100  * num_pressure_violations
    - 10   * max(0, 15 - min_pressure_head)
    - 2    * aged_pipe_pressure_stress
    - 1    * energy_penalty
    - 1    * valve_operation_penalty
    - 5    * service_disruption_penalty
~~~

Higher is better.

## 8.4 Aged Pipe Pressure Stress

For each pipe:

~~~text
pipe_pressure_exposure =
    aging_score * mean_pressure_near_pipe
~~~

Aggregate:

~~~text
aged_pipe_pressure_stress = sum(pipe_pressure_exposure over all pipes)
~~~

The controller should avoid simply increasing pump pressure everywhere, because that may protect low-pressure nodes while increasing burst risk in old pipes.

This is one of the key intellectual contributions of the project.

---

# 9. Visualization Requirements

The Streamlit app should include at minimum:

## 9.1 Network Map

Show:

- nodes,
- pipes,
- pipe color by aging score,
- node color by pressure status,
- valve/pump icons or labels,
- selected pipe/node details.

## 9.2 Pressure Dashboard

Show:

- minimum pressure head,
- number of nodes below 15 m,
- number of marginal nodes,
- highest pressure node,
- time-series pressure if available.

## 9.3 Aging Dashboard

Show:

- top 10 most aged pipes,
- aging score distribution,
- material-based risk summary,
- repair/leak history summary,
- high-criticality aged pipes.

## 9.4 Control Recommendation Panel

Show:

- recommended action,
- why it was recommended,
- expected effect,
- pressure after action,
- risks and trade-offs.

## 9.5 Head Loss Visualization

Show:

- pipe-level head loss gradient,
- abnormal head loss segments,
- possible causes:
  - old rough pipe,
  - partially closed valve,
  - high demand,
  - leak,
  - topological bottleneck.

---

# 10. MVP Implementation Plan

## Phase 0 — Repository Setup

Deliverables:

- `pyproject.toml`
- `requirements.txt`
- package structure under `src/`
- basic README
- pytest setup

Success criteria:

- `pytest` runs.
- imports work.
- no circular import problems.

## Phase 1 — Mock Data Generator

Implement:

- synthetic network generator,
- nodes.csv,
- pipes.csv,
- valves.csv,
- sensors.csv,
- sensor_timeseries.csv.

The generated network should include:

- at least 20 nodes,
- at least 25 pipes,
- at least 3 loops,
- at least 5 valves,
- at least 1 reservoir,
- optional pump,
- mixed pipe materials,
- mixed installation years,
- varied elevations,
- realistic-ish demand distribution.

Success criteria:

- generated network is connected,
- all pipe endpoints exist,
- all IDs are unique,
- all required columns exist.

## Phase 2 — Aging Score

Implement:

- `compute_pipe_aging_score(pipe_row, current_year)`
- `compute_all_aging_scores(pipes_df)`
- component-level score output.

Output should include:

~~~text
pipe_id
aging_score
age_component
material_component
repair_component
leak_history_component
geometry_component
soil_component
traffic_component
pressure_stress_component
topology_component
~~~

Success criteria:

- aging scores are in `[0, 1]`,
- old cast iron pipes score higher than new PVC pipes under comparable conditions,
- leak/repair history increases score,
- tests verify monotonic behavior.

## Phase 3 — Hydraulic Parameter Mapping

Implement:

- `adjust_roughness_by_aging`
- `estimate_minor_loss_k`
- `estimate_leak_probability`
- `estimate_burst_probability`

Success criteria:

- higher aging score lowers Hazen-Williams C,
- higher bend/valve count increases minor loss,
- higher aging score increases leak and burst risk.

## Phase 4 — Hydraulic Simulation

Implement:

- WNTR model builder from CSV,
- simulation runner,
- pressure result extractor,
- pipe flow extractor,
- head loss gradient calculation.

Success criteria:

- simulation runs on mock network,
- pressure table is produced,
- low-pressure nodes can be detected,
- head loss gradient table is produced.

## Phase 5 — Control Recommendation

Implement:

- baseline pressure check,
- candidate action generation,
- candidate simulation,
- action scoring,
- ranked recommendations.

Initial action types:

- increase pump head,
- reduce pump head,
- open valve,
- close valve,
- dispatch inspection,
- no action.

Success criteria:

- if low pressure exists, system proposes pressure-improving action,
- if aged pipes face high pressure, system penalizes excessive pressure,
- recommendations include explanations.

## Phase 6 — Streamlit App

Implement:

- network visualization,
- aging score dashboard,
- pressure status dashboard,
- control recommendation panel.

Success criteria:

- `streamlit run app/streamlit_app.py` works,
- mock data can be regenerated,
- visual output is understandable,
- user can select a scenario.

---

# 11. Scenario Design

Implement at least 4 scenarios.

## Scenario A — Normal Operation

- All nodes above 15 m.
- No severe head loss.
- Control recommendation: no action.

## Scenario B — Aging-Induced Head Loss

- One old cast iron path has low C value.
- Downstream nodes approach or fall below 15 m.
- System identifies aged high-loss pipes.

Expected recommendation:

- inspect/rehabilitate aged pipe,
- temporary pump adjustment,
- reroute if valve topology allows.

## Scenario C — Suspected Leak

- Inject abnormal pressure drop and flow increase.
- Pressure residual appears around a specific area.
- System flags candidate leak zone.

Expected recommendation:

- isolate suspected segment if feasible,
- dispatch inspection,
- avoid full network overpressure.

## Scenario D — Overpressure on Aged Pipe

- All demand nodes have enough pressure.
- But highly aged pipes experience excessive pressure.
- System should recommend pressure reduction or PRV adjustment.

Expected recommendation:

- reduce pump/PRV pressure if service constraint remains satisfied,
- prioritize aged high-pressure pipe for inspection.

---

# 12. Tests

## 12.1 Aging Score Tests

Test cases:

- New PVC pipe should have low aging score.
- Old cast iron pipe should have high aging score.
- Increasing repair count should increase score.
- Increasing leak history should increase score.
- Lower soil pH should increase score.
- Higher traffic load should increase score.

## 12.2 Hydraulic Mapping Tests

Test cases:

- Higher aging score decreases adjusted roughness C.
- Higher bend count increases minor loss K.
- Higher aging score increases leak probability.
- Burst risk increases nonlinearly with aging score.

## 12.3 Pressure Constraint Tests

Test cases:

- Nodes below 15 m are correctly flagged.
- Nodes above 15 m are not flagged.
- Pressure status labels are correct.

## 12.4 Mock Data Tests

Test cases:

- Network graph is connected.
- Every pipe endpoint exists in nodes.
- Required columns are present.
- No negative pipe length.
- No zero or negative diameter.
- Installation year is plausible.
- Aging score can be computed for all pipes.

## 12.5 Controller Tests

Test cases:

- If no pressure violation and no overpressure stress, recommend no action.
- If low-pressure violation exists, recommend pressure-improving action.
- If aged-pipe overpressure exists, penalize excessive pump increase.
- All recommendations include explanatory text.

---

# 13. Important Modeling Distinctions

## 13.1 Aging Score Is Not the Same as Criticality

A physically old pipe and a critical pipe are different concepts.

Example:

- A small dead-end pipe may be very old but low criticality.
- A newer transmission main may be high criticality because many nodes depend on it.

Therefore, ideal model should separate:

~~~text
condition_score: how degraded the pipe is
criticality_score: how much damage occurs if it fails
risk_score: condition × probability × consequence
~~~

For MVP, keep them close but document the distinction.

## 13.2 Hydraulic Roughness Is Not the Same as Burst Risk

Internal roughness affects head loss.

Burst risk depends on:

- wall condition,
- corrosion,
- pressure,
- pressure transients,
- soil/external loads,
- previous failures.

Do not pretend one scalar explains everything.

## 13.3 Low Pressure Is Not Always Caused by Aging

Possible causes:

- high demand,
- pump failure,
- closed valve,
- partially closed valve,
- leak,
- sensor error,
- incorrect model calibration,
- elevation difference,
- old rough pipe.

The system should present possible causes, not overclaim certainty.

## 13.4 High Pressure Can Be Dangerous

A naive controller may increase pressure to satisfy low-pressure nodes.  
But high pressure can worsen leakage and burst risk, especially in old pipes.

The controller must explicitly penalize high pressure around aged pipes.

This is central to the project.

---

# 14. Suggested Core Classes

## 14.1 Schemas

Use Pydantic if convenient.

~~~python
class PipeRecord(BaseModel):
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
~~~

~~~python
class AgingScoreResult(BaseModel):
    pipe_id: str
    aging_score: float
    components: dict[str, float]
~~~

~~~python
class HydraulicPipeParams(BaseModel):
    pipe_id: str
    base_roughness_c: float
    adjusted_roughness_c: float
    minor_loss_k: float
    leak_probability: float
    burst_probability: float
~~~

~~~python
class PressureViolation(BaseModel):
    node_id: str
    pressure_head_m: float
    threshold_m: float = 15.0
    severity: str
~~~

~~~python
class ControlRecommendation(BaseModel):
    action_id: str
    action_type: str
    target_id: str | None
    description: str
    expected_effect: str
    score: float
    risks: list[str]
    affected_nodes: list[str]
    affected_pipes: list[str]
~~~

---

# 15. Suggested Main CLI

Create a simple CLI or script commands.

~~~bash
python -m aging_water_network.data.mock_generator --out data/mock --nodes 30
python -m aging_water_network.hydraulics.simulator --data data/mock
python -m aging_water_network.control.controller --data data/mock --scenario aging_headloss
streamlit run app/streamlit_app.py
~~~

If CLI is too much for MVP, provide scripts:

~~~text
scripts/
  generate_mock_data.py
  run_simulation.py
  run_control_demo.py
~~~

---

# 16. README Expectations

The README should include:

1. Project summary.
2. Why aging-aware control matters.
3. Installation instructions.
4. How to generate mock data.
5. How to run simulation.
6. How to run Streamlit dashboard.
7. Explanation of aging score.
8. Explanation of pressure-head constraint.
9. Screenshots or expected dashboard views.
10. Limitations.

---

# 17. App UX Requirements

The Streamlit app should be understandable to a civil/environmental engineering professor.

Avoid overly technical UI clutter.

Recommended layout:

## Page 1 — Overview

- Total nodes
- Total pipes
- Minimum pressure head
- Number of low-pressure nodes
- Number of high-risk aged pipes
- Recommended action summary

## Page 2 — Network Map

- Pipe color: aging score
- Node color: pressure status
- Tooltip: pipe/node details

## Page 3 — Aging Model

- Table of top risk pipes
- Component breakdown chart
- Material risk summary

## Page 4 — Hydraulic Results

- Pressure table
- Head loss gradient table
- Low-pressure node list

## Page 5 — Control Recommendation

- Ranked actions
- Explanation
- Before/after comparison

---

# 18. Definition of Done

The repository is considered MVP-complete when:

1. Mock data can be generated.
2. Aging scores are computed for every pipe.
3. Aging scores modify hydraulic parameters.
4. Hydraulic simulation runs.
5. Pressure violations are detected.
6. At least one control recommendation is generated.
7. A Streamlit dashboard visualizes the result.
8. Tests pass.
9. README explains the system clearly.
10. The project can be demonstrated in under 5 minutes.

---

# 19. Demonstration Script

Use this narrative for demo:

1. Start with a normal mock water network.
2. Show that every demand node has pressure head above 15 m.
3. Increase aging severity in a specific pipe corridor.
4. Show that roughness decreases and head loss increases.
5. Show downstream pressure dropping near or below 15 m.
6. Show the system flagging vulnerable pipes and low-pressure nodes.
7. Run the controller.
8. Show recommended action:
   - temporary pressure adjustment,
   - rerouting through an alternate valve path,
   - inspection/rehabilitation priority.
9. Show that naive pressure increase may solve low pressure but increases stress on old pipes.
10. Explain why aging-aware control is superior to pressure-only control.

---

# 20. Intellectual Contribution

The key idea is not merely detecting low pressure.

The key idea is:

> Use pipe aging metadata to update hydraulic parameters and operational risk, then choose control actions that maintain minimum service pressure while avoiding excessive stress on vulnerable pipes.

This combines:

- water distribution hydraulics,
- infrastructure aging,
- graph topology,
- anomaly detection,
- operational control,
- digital twin thinking.

This should be implemented as an engineering-grade proof-of-concept, not as a cosmetic AI demo.

---

# 21. Non-Goals

Do not spend time on:

- real-world deployment,
- real SCADA connection,
- real GIS import,
- real calibrated failure probability,
- production-grade pump optimization,
- deep learning,
- cloud infrastructure,
- authentication,
- fancy UI before simulation works.

Do not build a chatbot as the main feature.

The main feature is the simulator and controller.

---

# 22. Future Extensions

After MVP, possible extensions include:

## 22.1 Machine Learning Failure Risk Model

Train a model using synthetic or real pipe failure labels.

Possible models:

- logistic regression,
- random forest,
- XGBoost,
- survival analysis,
- Bayesian failure model.

## 22.2 Sensor-Based Calibration

Use sensor residuals to update:

- roughness coefficient,
- demand estimate,
- leak likelihood,
- valve status.

## 22.3 Leak Localization

Inject virtual leaks into candidate nodes or pipes and compare pressure residual signatures.

## 22.4 Multi-Objective Optimization

Use optimization to balance:

- pressure service,
- energy cost,
- leakage risk,
- burst risk,
- water age,
- valve operation cost.

## 22.5 GIS Integration

Add:

- real coordinates,
- map tiles,
- district metered areas,
- pipe replacement planning.

## 22.6 Vision-Language Integration

Use visual outputs from the hydraulic model and ask a multimodal model to summarize:

- low-pressure zones,
- abnormal head loss regions,
- likely causes,
- recommended field inspection targets.

This should remain secondary to the numerical hydraulic model.

---

# 23. Implementation Attitude for Coding Agent

Build this like a serious engineering prototype.

Prioritize:

1. Correct data flow.
2. Clear interfaces.
3. Deterministic behavior.
4. Tests.
5. Explainable formulas.
6. Useful visualizations.
7. Modular architecture.

Avoid:

1. Unclear magic constants.
2. Unexplained ML.
3. UI-first development.
4. Unvalidated mock data.
5. One giant script.
6. Overclaiming real-world accuracy.

Every important assumption should be represented in code or config.

Every output should be inspectable.

Every risk score should be explainable.

---

# 24. First Concrete Task List

Start by implementing the following in order:

1. Create repo structure.
2. Create `schemas.py`.
3. Create `mock_generator.py`.
4. Generate connected mock network.
5. Implement `scoring.py`.
6. Implement `roughness.py`.
7. Add tests for aging score and roughness mapping.
8. Implement basic network visualization.
9. Implement WNTR model builder.
10. Run hydraulic simulation.
11. Detect pressure violations.
12. Implement simple controller.
13. Build Streamlit app.
14. Add README demo instructions.

Do not skip tests.

Do not build the dashboard before the simulation pipeline works.

---

# 25. Minimal Mathematical Summary

## Pressure head constraint

~~~text
P_i >= 15 m
~~~

for every demand node `i`.

## Aging-adjusted roughness

~~~text
C_pipe = C_base(material) × (1 - α × aging_score)
~~~

where:

~~~text
0 ≤ aging_score ≤ 1
0 ≤ α ≤ 0.5
~~~

## Leak risk index

~~~text
leak_risk = base_leak + β × aging_score
~~~

## Burst risk index

~~~text
burst_risk = base_burst
           + γ × aging_score²
           + δ × pressure_stress
           + η × leak_history
~~~

## Aged pressure stress

~~~text
aged_pressure_stress = Σ aging_score_pipe × mean_pressure_near_pipe
~~~

## Controller objective

~~~text
maximize:
    service_pressure_score
  - pressure_violation_penalty
  - aged_pipe_stress_penalty
  - energy_penalty
  - valve_operation_penalty
  - service_disruption_penalty
~~~

---

# 26. Final Expected Output

At the end, the repo should allow this workflow:

~~~bash
# 1. Install
pip install -r requirements.txt

# 2. Generate mock data
python scripts/generate_mock_data.py

# 3. Run simulation
python scripts/run_simulation.py

# 4. Run control recommendation demo
python scripts/run_control_demo.py

# 5. Launch dashboard
streamlit run app/streamlit_app.py
~~~

Expected console output should include:

~~~text
Generated mock network:
- nodes: 30
- pipes: 38
- valves: 8
- sensors: 10

Aging model:
- high-risk pipes: 5
- max aging score: 0.86

Hydraulic simulation:
- minimum pressure head: 13.8 m
- pressure violations: 3 nodes
- critical head loss pipes: 2

Recommended action:
1. Increase pump head by 2.0 m and open valve V3.
2. Dispatch inspection to pipe P12.
3. Avoid larger pressure increase because P4 and P7 are highly aged and already over-stressed.
~~~

The project should make the following idea visually and numerically obvious:

> Aging-aware control is better than naive pressure control because it maintains service pressure while reducing unnecessary stress on vulnerable pipes.