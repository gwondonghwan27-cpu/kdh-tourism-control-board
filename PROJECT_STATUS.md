# Project Status

## 1. Project Purpose

This project is an EPANET `.inp` import based control board for aging-aware water distribution networks. The product direction is now an operator-facing `EPANET + GIS + real-time pressure heatmap` digital twin, rather than only an aging-analysis dashboard.

The intended final system should:

1. Automatically create a water-network model from EPANET `.inp` files.
2. Let users review and correct imported model assets.
3. Stay compatible with EPANET/WNTR.
4. Render the network in a GIS-first map workflow with pressure/flow/leak/DMA layers.
5. Combine SCADA-style telemetry, aging analysis, and hydraulic simulation.
6. Recommend control actions and evaluate side effects.
7. Run repeated real-time or virtual real-time simulations.

Current codebase status: this is an MVP/prototype that combines EPANET INP import, aging scoring, fallback hydraulic estimates, live dashboard controls, and rule-based or fallback-simulation-assisted recommendations. Mock data remains available for tests and demos, but the latest user-facing HTML dashboard starts from an empty map instead of auto-rendering the mock network.

## 2. Current Main Entrypoint

The current main execution file is:

```text
streamlit_app.py
```

`streamlit_app.py` is a thin Streamlit Cloud wrapper. It imports and runs:

```text
app/streamlit_html_dashboard.py
```

The latest user-facing dashboard is therefore the HTML dashboard embedded in Streamlit, not the older Streamlit-native analysis app.

## 3. Run Commands

Run the primary dashboard:

```bash
streamlit run streamlit_app.py
```

Run the explicit HTML dashboard Streamlit entrypoint:

```bash
streamlit run app/streamlit_html_dashboard.py
```

Run the legacy Streamlit-native analysis app:

```bash
streamlit run app/streamlit_legacy_app.py
```

Run the direct local HTML/dashboard API server:

```bash
python scripts/dashboard_server.py
```

Run tests:

```bash
python -m pytest
```

## 4. Major Folder Roles

```text
app/
```

Streamlit entrypoints. `streamlit_html_dashboard.py` is the latest dashboard wrapper. `streamlit_legacy_app.py` exposes the older Streamlit-native analysis app. The legacy drawing-recognition app has been removed.

```text
frontend/
```

HTML/CSS/JavaScript dashboard. This is the main interactive control board surface, including INP upload/parsing UI, network editing tools, live scenario controls, visualization, and browser-side recommendations.

```text
src/aging_water_network/
```

Core Python package. Important modules:

- `vision/`: legacy image/PDF/CAD recognition code has been removed; intake is EPANET `.inp` parsing only.
- `aging/scoring.py`, `aging/roughness.py`, `aging/risk.py`: aging score and hydraulic parameter mapping.
- `hydraulics/simulator.py`: deterministic fallback hydraulic simulation.
- `hydraulics/dynamic.py`: household demand aggregation and time-step simulation.
- `hydraulics/live.py`: live-control snapshot computation.
- `hydraulics/epanet_builder.py`: WNTR model builder, but not a full WNTR simulation runner.
- `control/`: action space, action evaluation, and backend recommendation ranking.
- `data/`: mock data generation, loading, and validation.
- `visualization/`: Plotly figures for the legacy app.

```text
data/mock/
```

Synthetic deterministic CSV data used by the dashboard and tests.

```text
data/recognition_test/
```

Sample recognition test images and generated recognition result JSON files.

```text
scripts/
```

CLI and server helpers, including mock-data generation, dynamic demo runs, control demo runs, simulation runs, and the dashboard server.

```text
tests/
```

Unit tests for aging score, legacy drawing recognition, fallback hydraulic behavior, dynamic demand, live control, plotting, pressure constraints, and recommendations.

```text
notebooks/
```

Demo notebooks for mock data generation, aging scoring, hydraulic simulation, and control recommendation.

```text
kdh-tourism-control-board/
```

Appears to be a nested copy of the project. It is currently untracked and should be reviewed before any deletion or consolidation.

## 5. Actually Implemented Features

- Primary Streamlit Cloud entrypoint that embeds the HTML dashboard.
- Browser-based network dashboard that starts from an empty EPANET `.inp` intake workflow instead of auto-loading the bundled mock CSV network.
- GIS-first operating console for pressure heatmap, virtual SCADA health, leak probability, and digital-twin readiness.
- Map layer toggles for pressure, leak probability, DMA grouping, and asset risk.
- EPANET `.inp` upload UI and browser-side parser.
- INP section conversion for `[JUNCTIONS]`, `[RESERVOIRS]`, `[PIPES]`, `[PUMPS]`, `[COORDINATES]`, and `[VERTICES]`.
- Dashboard asset export from parsed INP results: nodes, pipes, reservoirs, pumps, and warnings.
- User-side correction/editing in the HTML dashboard:
  - Apply parsed INP assets to the dashboard.
  - Add/delete Junctions.
  - Add/delete Pipes.
  - Edit Junction coordinates, elevation, demand, and DMA.
  - Edit Pipe length, diameter, roughness, material, minor loss, bend count, and valve count.
  - Add/delete Source/Pump assets.
- Deterministic aging score model.
- Aging-to-hydraulic-parameter mapping, including adjusted roughness and leak/burst probability estimates.
- Deterministic fallback hydraulic simulation.
- Household demand aggregation into node-level time series.
- Virtual real-time/time-step simulation over mock demand data.
- Live control snapshot computation with demand overrides, pipe overrides, leak injection, source-head control, and leak candidate ranking.
- Backend control action ranking using fallback simulator output.
- Frontend rule-based alerts and recommendation text.
- Tests for many core backend pieces and existing legacy drawing-recognition cases.

## 6. Mock/Demo-Level Features

- `data/mock/` is synthetic and deterministic, and is kept for tests, demos, and backend examples rather than as the active dashboard's initial map.
- Hydraulic results are fallback estimates, not calibrated EPANET/WNTR results.
- Frontend dashboard simulation in `frontend/app.js` is browser-side and approximate after an INP model is applied.
- Runtime edits in the HTML dashboard are browser-session state and are not persisted to a database or canonical project file.
- Demo scripts and notebooks are demonstration workflows rather than production pipelines.
- Legacy recognition test data is synthetic or small sample data, not a validated real drawing corpus.
- Gemini/PDF/CAD/image recognition has been removed from the active workflow.
- Control recommendations are explainable prototype recommendations, not validated operational control decisions.

## 7. Not Yet Implemented

- Full EPANET/WNTR simulation execution through `wntr.sim.EpanetSimulator` or equivalent.
- Export/import of corrected dashboard network state as a durable canonical project model.
- Persisted user correction workflow for imported INP results.
- Calibrated hydraulic model using real field data.
- Production-grade INP import/export workflow.
- Real-time telemetry ingestion.
- Repeated real-time simulation loop connected to live data.
- Quantitative side-effect evaluation based on actual EPANET/WNTR runs.
- End-to-end tests covering upload, correction, persistence, simulation, recommendation, and re-simulation.
- Clear cleanup of nested duplicate project folder and generated cache artifacts.

## 8. EPANET/WNTR Integration Status

Current state: partial compatibility layer only.

Implemented:

- `src/aging_water_network/hydraulics/epanet_builder.py` can build a `wntr.network.WaterNetworkModel` when WNTR is installed.
- Pipes, junctions, reservoirs, and pumps are mapped from project tables into a WNTR model.
- `pyproject.toml` declares WNTR as an optional dependency.

Not implemented:

- `run_hydraulic_simulation(prefer_wntr=True)` does not actually run WNTR simulation.
- Even when WNTR imports successfully, the simulator currently falls back to `run_fallback_simulation()`.
- There is no confirmed EPANET `.inp` export/import or WNTR result normalization path in the active simulator.

Conclusion: the code is EPANET/WNTR-ready in intent and partial model-building structure, but not yet EPANET/WNTR-backed in actual hydraulic computation.

## 9. EPANET INP Import Status

Current state: functional browser-side EPANET `.inp` parser for dashboard import.

Implemented:

- File type routing for `.inp` uploads.
- Browser-side parsing of EPANET sections.
- Unit conversion for US customary and SI EPANET flow units.
- Conversion of INP nodes, reservoirs, pipes, pumps, coordinates, and vertices to dashboard-ready assets.
- Pump connector links for visual/map continuity.
- Download of parsed assets from the dashboard.
- Application of parsed assets into the dashboard runtime state.

Limitations:

- Correction is interactive but not persisted as a canonical saved model.
- INP import is currently frontend-side; backend validation/export should be added.
- Pump curves, controls, rules, tanks, valves, water quality, and energy sections are not yet fully represented in the active dashboard model.

## 10. Control Recommendation Status

Current state: hybrid prototype.

Backend:

- `src/aging_water_network/control/action_space.py` creates deterministic candidate actions.
- `src/aging_water_network/control/controller.py` evaluates actions through a simulator contract.
- `src/aging_water_network/control/evaluator.py` ranks actions using pressure violations, aged-pipe overpressure, and adjustment penalties.
- If the discovered simulator supports the required parameters, recommendations can use fallback hydraulic results.

Frontend:

- The active HTML dashboard displays recommendations from browser-side rule logic.
- It reacts to low pressure, leaks, overpressure, and aging/replacement ranking.

Limitations:

- Recommendations are not based on real WNTR/EPANET simulation.
- Frontend recommendations are mostly rule-based text.
- Side effects are described qualitatively or through fallback estimates, not through robust before/after hydraulic scenario runs.
- There is no persisted recommendation audit trail.

## 11. Next Development Priorities

1. Complete the GIS/EPANET MVP path.

   Prioritize INP import/export, GIS basemap integration, pressure/flow colormaps, and time-slider playback. This is the highest-impact path for field engineers and utility operators.

2. Clarify and consolidate project structure.

   Keep `streamlit_app.py` and `app/streamlit_html_dashboard.py` as the primary execution path. Review the nested `kdh-tourism-control-board/` copy before removing or archiving it.

3. Implement actual WNTR/EPANET-backed simulation.

   Update `run_hydraulic_simulation(prefer_wntr=True)` so it builds the WNTR model, runs the simulator, and normalizes WNTR node/link results into the same DataFrame contract used by fallback simulation.

4. Persist corrected imported model results.

   Add a canonical save/load path for dashboard-edited nodes, pipes, reservoirs, pumps, and valves. The corrected network should become the input to Python hydraulic simulation and recommendation evaluation.

5. Connect recommendations to evaluated scenarios.

   Move the active dashboard recommendation flow toward backend evaluated actions: baseline simulation, candidate action simulation, side-effect metrics, and ranked before/after comparison.

6. Add live telemetry and leak detection.

   Introduce a SCADA adapter contract, pressure residual analysis, minimum-night-flow scoring, leak probability map output, and event alarm history.

7. Expand end-to-end tests.

   Add tests for WNTR execution, recognized asset application, corrected model persistence, EPANET-compatible export/import, recommendation before/after evaluation, and repeated time-step simulation.
