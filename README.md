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

## Run The HTML Dashboard

```bash
streamlit run streamlit_app.py
```

This is the primary shareable dashboard. It embeds the same HTML, CSS, JavaScript, and mock CSV data used by the local static dashboard, so Streamlit users see the same water-network board rather than a separate Streamlit recreation.

The dashboard includes:

- 10-minute time playback with play and speed controls.
- Demand, source-head, pump-head, and multi-leak scenario controls.
- Editable junction and pipe assets.
- CAD-like pipe drawing and deletion.
- Leak pipe highlighting and per-pipe leak amounts.
- Pipe flow direction, width-by-flow, pressure safety status, and zoomable network map.

## Run The Legacy Streamlit Analysis App

```bash
streamlit run app/streamlit_legacy_app.py
```

This older Streamlit-native app is kept for analytical tabs and Python-side experiments. It does not match the current HTML dashboard screen.

The legacy app includes six tabs:

- Overview: node/pipe counts, minimum pressure, low-pressure count, high-risk pipe count, and top action.
- Network Map: Plotly map with pipe aging color, node pressure status, valves, pumps, and pipe details.
- Aging Model: top aged pipes, aging-score distribution, material summary, and component breakdown.
- Hydraulic Results: pressure table, low-pressure list, head-loss gradient table, and pressure sensor time series.
- Dynamic Demand: household demand time series, node demand aggregation, and minimum source/pump head by time step.
- Live Control: interactively change time-step demand, source pressure, leak location, and leak magnitude, then see pressure and leak-suspect maps update.
- Control Recommendation: ranked actions with expected effect and risks.

## Deploy The Exact HTML Dashboard In Streamlit

To share the same interactive HTML dashboard through Streamlit, run:

```bash
streamlit run streamlit_app.py
```

You can also run the explicit app file:

```bash
streamlit run app/streamlit_html_dashboard.py
```

This Streamlit entrypoint embeds the HTML dashboard directly from `frontend/index.html`, `frontend/styles.css`, and `frontend/app.js`. On Streamlit Cloud, drawing recognition is handled directly by Streamlit/Python from the sidebar upload control, then injected into the embedded dashboard as recognized network assets. This avoids localhost iframe URLs such as `127.0.0.1:5173`, which are not reachable from mobile or public Streamlit sessions.

You can also run the same server directly without Streamlit:

```bash
python scripts/dashboard_server.py
```

For Streamlit Community Cloud:

1. Push this repository to GitHub.
2. Create a new Streamlit app from the GitHub repository.
3. Set the main file path to `streamlit_app.py`.
4. Let Streamlit install dependencies from `requirements.txt`.

The embedded HTML dashboard currently uses the mock data bundled in this repository. Runtime edits inside the map are browser-session state, so they are useful for design simulation and demonstrations but are not persisted to a database yet.

## Run JPG/PNG Drawing Recognition

To test the first image-recognition pipeline for water-network drawings:

```bash
streamlit run app/drawing_recognition_app.py
```

For Streamlit Community Cloud, create a second app from the same GitHub repository and set its main file path to:

```text
app/drawing_recognition_app.py
```

This tool accepts `.jpg`, `.jpeg`, and `.png` drawings. It runs OpenCV first to extract line, node/symbol, and pipe candidates, then builds a first internal binary payload from that structure. Gemini Vision can be enabled from the sidebar when `GEMINI_API_KEY` or `GOOGLE_API_KEY` is configured, or when an API key is entered in the app.

The recognition output also creates dashboard-ready asset candidates:

- `recognized_network_assets.json`: nodes, pipes, virtual reservoir, and warnings.
- `nodes.csv`: first-pass junction/reservoir coordinates for the HTML dashboard.
- `pipes.csv`: first-pass pipe endpoints, length, diameter, material, and aging metadata.
- `reservoirs.csv`: a virtual source reservoir for previewing the imported network.

The image pipeline should be treated as a drafting assistant. OpenCV extracts geometry deterministically, Gemini provides semantic hints, and the resulting network should still be checked and edited on the dashboard before use.

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
streamlit run streamlit_app.py
```

## Limitations

- Mock data is synthetic and deterministic.
- Current fallback hydraulics are interpretable estimates, not a calibrated EPANET solution.
- Control actions are ranked by transparent rules until the full controller API is implemented.
- The system should not be used to make real operational or safety decisions without real calibration, validation, and domain review.
