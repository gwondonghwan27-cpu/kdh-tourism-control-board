# Aging-Aware Hydraulic Digital Twin

Proof-of-concept simulator for an aging water distribution network. The project connects deterministic mock asset data, household-level dynamic demand, explainable pipe-aging scores, hydraulic pressure-head estimates, head-loss risk, and rule-based control recommendations.

This is not a real failure-prediction product. It is a local engineering prototype showing how aging-related pipe metadata can be coupled to hydraulic simulation and control logic.

## Why Aging-Aware Control Matters

Traditional pressure control can fix low-pressure nodes by raising pump head everywhere. In an old network, that can move risk into fragile pipe corridors by increasing leak and burst exposure. This project keeps both constraints visible:

- keep demand nodes above the minimum pressure-head constraint,
- avoid unnecessary pressure stress on highly aged pipes.

The default minimum service constraint is:

```text
pressure head >= 15 m
```

## Install

Use Python 3.11 or 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

For test-only dependency installation from `requirements.txt`:

```bash
python -m pip install -r requirements.txt
```

## Generate Mock Data

The app can generate mock data automatically, but the CSV files can also be generated directly:

```bash
PYTHONPATH=src python -m aging_water_network.data.mock_generator --out data/mock --scenario aging_headloss
```

Available scenarios:

- `normal`
- `aging_headloss`
- `suspected_leak`
- `overpressure_aged`

## Run The Dashboard

```bash
streamlit run app/streamlit_app.py
```

The dashboard includes six tabs:

- Overview: node/pipe counts, minimum pressure, low-pressure count, high-risk pipe count, and top action.
- Network Map: Plotly map with pipe aging color, node pressure status, valves, pumps, and pipe details.
- Aging Model: top aged pipes, aging-score distribution, material summary, and component breakdown.
- Hydraulic Results: pressure table, low-pressure list, head-loss gradient table, and pressure sensor time series.
- Dynamic Demand: household demand time series, node demand aggregation, and minimum source/pump head by time step.
- Live Control: interactively change time-step demand, source pressure, leak location, and leak magnitude, then see pressure and leak-suspect maps update.
- Control Recommendation: ranked actions with expected effect and risks.

## Run The Exact HTML Dashboard In Streamlit

To share the same interactive HTML dashboard through Streamlit, run:

```bash
streamlit run app/streamlit_html_dashboard.py
```

This Streamlit entrypoint embeds the current static dashboard from `frontend/index.html`, `frontend/styles.css`, `frontend/app.js`, and the mock CSV files under `data/mock`. It is meant for Streamlit Community Cloud or any Streamlit server where other users should see the same dashboard UI that is available from the local HTML version.

For Streamlit Community Cloud:

1. Push this repository to GitHub.
2. Create a new Streamlit app from the GitHub repository.
3. Set the main file path to `app/streamlit_html_dashboard.py`.
4. Let Streamlit install dependencies from `requirements.txt`.

The embedded HTML dashboard currently uses the mock data bundled in this repository. Runtime edits inside the map are browser-session state, so they are useful for design simulation and demonstrations but are not persisted to a database yet.

## Dynamic Household Demand

Mock data includes:

- `households.csv`: household/customer records assigned to demand nodes.
- `household_demand_timeseries.csv`: 15-minute household demand readings.

The dynamic simulator aggregates household readings into node demand at each time step, runs the hydraulic model, and computes the minimum source head needed to keep every demand node above the 15 m pressure-head constraint. By default this dynamic calculation ignores minor-loss coefficients, which matches the simplified operating assumption that small local losses can be omitted for a first control estimate.

Run it directly:

```bash
PYTHONPATH=src python scripts/run_dynamic_demo.py --data-dir data/mock
```

## Live Control Workflow

Open the dashboard and use the `Live Control` tab to:

- select a 15-minute time step,
- scale all node demands,
- edit each node's demand multiplier or extra demand,
- switch between automatic minimum source-head control and manual source-head control,
- inject a leak at a selected pipe or node,
- view highlighted low-pressure nodes and leak-suspect pipe candidates on the network map.

## Aging Score

The aging score is deterministic and ranges from `0.0` to `1.0`.

It combines:

- age versus design life,
- material risk,
- repair history,
- leak history,
- geometry and valve/bend burden,
- soil corrosivity,
- traffic load,
- pressure-stress history,
- topology proxy.

The score is then mapped into hydraulic parameters such as adjusted Hazen-Williams roughness, leak probability, and burst probability.

## Hydraulic Results

The project is designed to support a WNTR/EPANET-compatible simulator. The MVP includes a deterministic local simulator so the full data, aging, hydraulic, controller, and dashboard workflow remains runnable even when WNTR is not installed.

Key outputs:

- pressure head by node,
- pressure status against the 15 m minimum,
- pipe head-loss gradient,
- abnormal head-loss segments,
- recommended operational actions.
- time-varying total demand and required pump/source head.

## Expected Dashboard Views

Without screenshots, a successful run should show:

- a coordinate network map with colored pipe segments and pressure-coded nodes,
- low-pressure nodes highlighted in red and marginal nodes in orange,
- high-aging pipe bars near the top of the Aging Model tab,
- head-loss gradient bars with warning and critical threshold lines,
- a dynamic demand chart showing peak household use and required pump head,
- a ranked control table with action type, target, explanation, expected effect, score, and risk notes.

## Test And Smoke Commands

```bash
python -m compileall app src
python -m pytest
streamlit run app/streamlit_app.py
```

## Limitations

- Mock data is synthetic and deterministic.
- Current fallback hydraulics are interpretable estimates, not a calibrated EPANET solution.
- Control actions are ranked by transparent rules until the full controller API is implemented.
- The system should not be used to make real operational or safety decisions without real calibration, validation, and domain review.
