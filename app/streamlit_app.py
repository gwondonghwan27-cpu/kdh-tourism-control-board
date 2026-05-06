"""Streamlit frontend for the aging-aware water-network prototype."""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aging_water_network.config import (  # noqa: E402
    BASE_BURST_PROBABILITY,
    BASE_HW_C,
    BASE_LEAK_PROBABILITY,
    CURRENT_YEAR,
    DEFAULT_AGING_WEIGHTS,
    DEFAULT_DATA_DIR,
    DESIGN_LIFE_BY_MATERIAL,
    HEAD_LOSS_GRADIENT_CRITICAL,
    HEAD_LOSS_GRADIENT_WARNING,
    HIGH_PRESSURE_STRESS_M,
    LEAK_AGING_MULTIPLIER,
    MARGINAL_PRESSURE_HEAD_M,
    MATERIAL_RISK,
    MAX_C_DEGRADATION,
    MIN_PRESSURE_HEAD_M,
)
from aging_water_network.data.loaders import ensure_mock_data  # noqa: E402
from aging_water_network.data.mock_generator import SCENARIOS, generate_mock_network  # noqa: E402
from aging_water_network.hydraulics.dynamic import aggregate_household_demands, run_dynamic_demand_simulation  # noqa: E402
from aging_water_network.hydraulics.live import (  # noqa: E402
    DemandOverride,
    LiveScenarioState,
    LiveSimulationSnapshot,
    PipeOverride,
    compute_live_snapshot,
    live_state_cache_key,
)
from aging_water_network.visualization.network_plot import create_network_map  # noqa: E402
from aging_water_network.visualization.pressure_plot import (  # noqa: E402
    create_headloss_bar,
    create_pressure_bar,
    create_pressure_timeseries,
)
from aging_water_network.visualization.risk_plot import (  # noqa: E402
    create_aging_distribution,
    create_component_breakdown,
    create_material_summary,
    create_top_risk_bar,
)

try:  # noqa: E402
    from streamlit_plotly_events import plotly_events  # type: ignore
except Exception:  # pragma: no cover - optional UI dependency fallback
    plotly_events = None


@dataclass(frozen=True)
class DashboardState:
    tables: dict[str, pd.DataFrame]
    node_demand_timeseries: pd.DataFrame
    base_aging: pd.DataFrame
    source_note: str


def main() -> None:
    try:
        from app.streamlit_html_dashboard import main as render_html_dashboard
    except ModuleNotFoundError:
        from streamlit_html_dashboard import main as render_html_dashboard

    render_html_dashboard()


def legacy_main() -> None:
    st.set_page_config(page_title="Aging Water Network", layout="wide")
    st.title("Aging-Aware Hydraulic Digital Twin")
    st.caption("Live-control simulator: demand, pressure, leak, and aging edits drive every panel.")

    scenario, data_dir, regenerate = render_sidebar()
    state = load_dashboard_state(data_dir, scenario, regenerate)
    initialize_live_session_state(state)

    if state.source_note:
        st.info(state.source_note)

    panel = st.sidebar.radio(
        "Panel",
        [
            "Live Control",
            "Overview",
            "Network Map",
            "Aging Model",
            "Hydraulic Results",
            "Dynamic Demand",
            "Control Recommendation",
        ],
        index=0,
        key="active_panel",
    )
    if panel == "Live Control":
        snapshot = render_live_control(state)
    else:
        snapshot = compute_snapshot_from_session(state)

    if panel == "Overview":
        render_overview(state, snapshot)
    elif panel == "Network Map":
        render_network_map(state, snapshot)
    elif panel == "Aging Model":
        render_aging_model(state, snapshot)
    elif panel == "Hydraulic Results":
        render_hydraulic_results(state, snapshot)
    elif panel == "Dynamic Demand":
        render_dynamic_demand(state, snapshot)
    elif panel == "Control Recommendation":
        render_control_recommendations(state, snapshot)


def render_sidebar() -> tuple[str, Path, bool]:
    st.sidebar.header("Run setup")
    scenario = st.sidebar.selectbox("Scenario", SCENARIOS, index=SCENARIOS.index("aging_headloss"))
    data_dir_text = st.sidebar.text_input("Data directory", str(REPO_ROOT / DEFAULT_DATA_DIR))
    regenerate = st.sidebar.button("Regenerate mock data", type="primary")
    st.sidebar.caption("Regeneration overwrites the selected mock CSV directory with deterministic data.")
    return scenario, Path(data_dir_text).expanduser(), regenerate


@st.cache_data(show_spinner=False)
def _load_tables(data_dir: str, scenario: str, regenerate: bool) -> dict[str, pd.DataFrame]:
    data_path = Path(data_dir)
    if regenerate:
        return generate_mock_network(data_path, scenario=scenario)
    return ensure_mock_data(data_path, scenario=scenario)


def load_dashboard_state(data_dir: Path, scenario: str, regenerate: bool) -> DashboardState:
    try:
        tables = _load_tables(str(data_dir), scenario, regenerate)
    except Exception as exc:  # pragma: no cover - Streamlit runtime path
        st.error(f"Could not load or generate mock data: {exc}")
        st.stop()

    source_messages: list[str] = []
    aging = compute_aging_scores(tables["pipes"])
    node_demand_timeseries = _aggregate_node_demands(tables)
    source_messages.append("Live Control is the active state for every dashboard panel.")

    return DashboardState(
        tables=tables,
        node_demand_timeseries=node_demand_timeseries,
        base_aging=aging,
        source_note=" ".join(source_messages),
    )


@st.cache_data(show_spinner=False)
def _aggregate_node_demands(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return aggregate_household_demands(tables)


@st.cache_data(
    show_spinner=False,
    hash_funcs={
        LiveScenarioState: live_state_cache_key,
    },
)
def _compute_live_snapshot_cached(
    tables: dict[str, pd.DataFrame],
    node_demand_timeseries: pd.DataFrame,
    live_state: LiveScenarioState,
) -> LiveSimulationSnapshot:
    return compute_live_snapshot(tables, node_demand_timeseries, live_state)


def initialize_live_session_state(state: DashboardState) -> None:
    timestamps = [
        pd.Timestamp(value)
        for value in sorted(pd.to_datetime(state.node_demand_timeseries["timestamp"]).dropna().unique())
    ]
    if timestamps:
        default_timestamp = timestamps[min(28, len(timestamps) - 1)]
        current_timestamp = st.session_state.get("live_timestamp")
        if current_timestamp is None or pd.Timestamp(current_timestamp) not in timestamps:
            st.session_state.live_timestamp = default_timestamp
    st.session_state.setdefault("live_global_multiplier", 1.0)
    st.session_state.setdefault("live_include_minor_losses", False)
    st.session_state.setdefault("live_pressure_mode", "auto")
    st.session_state.setdefault("live_manual_source_head", float(state.tables["reservoirs"].iloc[0]["head_m"]))
    st.session_state.setdefault("live_leak_enabled", True)
    st.session_state.setdefault("live_leak_target_type", "pipe")
    st.session_state.setdefault("live_leak_target_id", "P14")
    st.session_state.setdefault("live_leak_demand_lps", 2.0)
    st.session_state.setdefault("live_demand_overrides", {})
    st.session_state.setdefault("live_click_edit_mode", False)
    pipe_ids = state.tables["pipes"]["pipe_id"].astype(str).tolist()
    node_ids = state.tables["nodes"]["node_id"].astype(str).tolist()
    if "selected_pipe_id" not in st.session_state or st.session_state.selected_pipe_id not in pipe_ids:
        st.session_state.selected_pipe_id = pipe_ids[0]
    if "selected_node_id" not in st.session_state or st.session_state.selected_node_id not in node_ids:
        st.session_state.selected_node_id = node_ids[0]
    if st.session_state.live_leak_target_type == "pipe" and st.session_state.live_leak_target_id not in pipe_ids:
        st.session_state.live_leak_target_id = pipe_ids[min(13, len(pipe_ids) - 1)]
    if st.session_state.live_leak_target_type == "node" and st.session_state.live_leak_target_id not in node_ids:
        st.session_state.live_leak_target_id = node_ids[0]
    st.session_state.setdefault("live_pipe_overrides", {})


def compute_snapshot_from_session(state: DashboardState) -> LiveSimulationSnapshot:
    live_state = live_state_from_controls(state)
    t0 = time.perf_counter()
    snapshot = _compute_live_snapshot_cached(state.tables, state.node_demand_timeseries, live_state)
    return replace(snapshot, elapsed_ms=(time.perf_counter() - t0) * 1000.0)


def live_state_from_controls(
    state: DashboardState,
    demand_editor: pd.DataFrame | None = None,
) -> LiveScenarioState:
    if demand_editor is not None:
        st.session_state.live_demand_overrides = demand_editor_to_overrides(demand_editor)

    demand_overrides = {
        str(node_id): DemandOverride(
            multiplier=float(values.get("multiplier", 1.0)),
            extra_demand_lps=float(values.get("extra_demand_lps", 0.0)),
        )
        for node_id, values in st.session_state.live_demand_overrides.items()
    }

    pipe_overrides = {
        str(pipe_id): PipeOverride(**override)
        for pipe_id, override in st.session_state.live_pipe_overrides.items()
    }
    return LiveScenarioState(
        timestamp=pd.Timestamp(st.session_state.live_timestamp),
        global_demand_multiplier=float(st.session_state.live_global_multiplier),
        demand_overrides=demand_overrides,
        pressure_mode=str(st.session_state.live_pressure_mode),
        manual_source_head_m=float(st.session_state.live_manual_source_head),
        include_minor_losses=bool(st.session_state.live_include_minor_losses),
        leak_enabled=bool(st.session_state.live_leak_enabled),
        leak_target_type=str(st.session_state.live_leak_target_type),
        leak_target_id=str(st.session_state.live_leak_target_id),
        leak_demand_lps=float(st.session_state.live_leak_demand_lps),
        pipe_overrides=pipe_overrides,
        selected_pipe_id=str(st.session_state.selected_pipe_id),
        selected_node_id=str(st.session_state.selected_node_id),
    )


def demand_editor_to_overrides(demand_editor: pd.DataFrame) -> dict[str, dict[str, float]]:
    demand_overrides: dict[str, dict[str, float]] = {}
    if demand_editor.empty:
        return demand_overrides
    for row in demand_editor.to_dict("records"):
        node_id = str(row["node_id"])
        multiplier = float(row.get("demand_multiplier", 1.0) or 1.0)
        extra = float(row.get("extra_demand_lps", 0.0) or 0.0)
        if abs(multiplier - 1.0) > 1e-9 or extra > 1e-9:
            demand_overrides[node_id] = {
                "multiplier": multiplier,
                "extra_demand_lps": extra,
            }
    return demand_overrides


def parse_clicked_object(events: list[dict[str, Any]], fig: Any | None = None) -> tuple[str, str] | None:
    if not events:
        return None
    custom = events[0].get("customdata")
    parsed = _parse_customdata_value(custom)
    if parsed:
        return parsed

    if fig is not None:
        try:
            curve_number = int(events[0].get("curveNumber"))
            point_number = int(events[0].get("pointNumber", events[0].get("pointIndex", 0)))
            trace_customdata = getattr(fig.data[curve_number], "customdata", None)
            if trace_customdata is not None:
                parsed = _parse_customdata_value(trace_customdata[point_number])
                if parsed:
                    return parsed
        except (TypeError, ValueError, IndexError):
            return None
    return None


def _parse_customdata_value(custom: Any) -> tuple[str, str] | None:
    if isinstance(custom, (list, tuple)) and custom:
        custom = custom[0]
    if isinstance(custom, str) and ":" in custom:
        kind, item_id = custom.split(":", 1)
        if kind in {"pipe", "node"} and item_id:
            return kind, item_id
    return None


def reset_pipe_widget_state(pipe_id: str) -> None:
    for suffix in ["material", "install", "repairs", "leaks", "diameter", "override_on", "aging_override"]:
        st.session_state.pop(f"pipe_{suffix}_{pipe_id}", None)


def compute_aging_scores(pipes: pd.DataFrame) -> pd.DataFrame:
    """Compute explainable aging scores from the CSV contract."""

    try:
        from aging_water_network.aging.scoring import compute_all_aging_scores

        result = compute_all_aging_scores(pipes)
        if {"pipe_id", "aging_score"}.issubset(result.columns):
            merged = pipes.merge(result, on="pipe_id", how="left")
            return supplement_aging_columns(merged)
    except Exception:
        pass

    rows: list[dict[str, Any]] = []
    weights = DEFAULT_AGING_WEIGHTS
    for _, pipe in pipes.iterrows():
        material = str(pipe.get("material", "unknown"))
        design_life = DESIGN_LIFE_BY_MATERIAL.get(material, DESIGN_LIFE_BY_MATERIAL["unknown"])
        age_component = np.clip((CURRENT_YEAR - float(pipe.get("install_year", CURRENT_YEAR))) / design_life, 0, 1)
        material_component = MATERIAL_RISK.get(material, MATERIAL_RISK["unknown"])
        repair_component = np.clip(float(pipe.get("repair_count", 0)) / 5, 0, 1)
        leak_component = np.clip(float(pipe.get("leak_history_count", 0)) / 3, 0, 1)
        geometry_component = np.clip(
            float(pipe.get("bend_count", 0)) / 5
            + float(pipe.get("valve_count", 0)) / 6
            + max(0.0, 250.0 - float(pipe.get("diameter_mm", 250))) / 400,
            0,
            1,
        )
        soil_component = np.clip(
            (7.0 - float(pipe.get("soil_ph", 7.0))) / 2.0
            + max(0.0, 2000.0 - float(pipe.get("soil_resistivity_ohm_cm", 3000))) / 2500,
            0,
            1,
        )
        traffic_component = np.clip(float(pipe.get("traffic_load_index", 0)), 0, 1)
        pressure_stress_component = np.clip(float(pipe.get("burst_history_count", 0)) / 2, 0, 1)
        topology_component = np.clip(float(pipe.get("valve_count", 0)) / 2, 0, 1)

        score = (
            weights["age"] * age_component
            + weights["material"] * material_component
            + weights["repair"] * repair_component
            + weights["leak_history"] * leak_component
            + weights["geometry"] * geometry_component
            + weights["soil"] * soil_component
            + weights["traffic"] * traffic_component
            + weights["pressure_stress"] * pressure_stress_component
            + weights["topology"] * topology_component
        )
        base_c = BASE_HW_C.get(material, BASE_HW_C["unknown"])
        adjusted_c = base_c * (1.0 - MAX_C_DEGRADATION * score)
        rows.append(
            {
                **pipe.to_dict(),
                "age_component": round(float(age_component), 4),
                "material_component": round(float(material_component), 4),
                "repair_component": round(float(repair_component), 4),
                "leak_history_component": round(float(leak_component), 4),
                "geometry_component": round(float(geometry_component), 4),
                "soil_component": round(float(soil_component), 4),
                "traffic_component": round(float(traffic_component), 4),
                "pressure_stress_component": round(float(pressure_stress_component), 4),
                "topology_component": round(float(topology_component), 4),
                "aging_score": round(float(np.clip(score, 0, 1)), 4),
                "base_roughness_c": round(float(base_c), 2),
                "adjusted_roughness_c": round(float(adjusted_c), 2),
                "leak_probability": round(float(BASE_LEAK_PROBABILITY + score * LEAK_AGING_MULTIPLIER), 4),
                "burst_probability": round(float(BASE_BURST_PROBABILITY + score**2 * 0.04), 4),
            }
        )
    return pd.DataFrame(rows)


def supplement_aging_columns(aging: pd.DataFrame) -> pd.DataFrame:
    frame = aging.copy()
    if "aging_score" not in frame.columns:
        frame["aging_score"] = 0.0
    frame["aging_score"] = pd.to_numeric(frame["aging_score"], errors="coerce").fillna(0.0).clip(0, 1)

    if "base_roughness_c" not in frame.columns:
        materials = frame["material"] if "material" in frame.columns else pd.Series("unknown", index=frame.index)
        frame["base_roughness_c"] = materials.map(BASE_HW_C).fillna(BASE_HW_C["unknown"])
    if "adjusted_roughness_c" not in frame.columns:
        frame["adjusted_roughness_c"] = frame["base_roughness_c"] * (1.0 - MAX_C_DEGRADATION * frame["aging_score"])
    if "leak_probability" not in frame.columns:
        frame["leak_probability"] = BASE_LEAK_PROBABILITY + frame["aging_score"] * LEAK_AGING_MULTIPLIER
    if "burst_probability" not in frame.columns:
        frame["burst_probability"] = BASE_BURST_PROBABILITY + frame["aging_score"] ** 2 * 0.04
    return frame


def compute_hydraulic_results(
    tables: dict[str, pd.DataFrame],
    aging: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        from aging_water_network.hydraulics.simulator import run_hydraulic_simulation

        result = run_hydraulic_simulation(tables=tables, prefer_wntr=False)
        node_results = result.get("node_results") if isinstance(result, dict) else None
        pipe_results = result.get("pipe_results") if isinstance(result, dict) else None
        if isinstance(node_results, pd.DataFrame) and isinstance(pipe_results, pd.DataFrame):
            pressure = normalize_pressure_results(node_results)
            headloss = normalize_headloss_results(pipe_results)
            if not pressure.empty and not headloss.empty:
                return pressure, headloss
    except Exception:
        pass

    nodes = tables["nodes"]
    pipes = tables["pipes"]
    reservoirs = tables.get("reservoirs", pd.DataFrame())
    pumps = tables.get("pumps", pd.DataFrame())
    valves = tables.get("valves", pd.DataFrame())

    reservoir_head = 64.0
    source_node = "R1"
    if not reservoirs.empty:
        reservoir_head = float(reservoirs.iloc[0].get("head_m", reservoir_head))
        source_node = str(reservoirs.iloc[0].get("node_id", source_node))
    pump_gain = 0.0
    if not pumps.empty:
        pump_gain = float((pumps.get("base_head_gain_m", pd.Series(dtype=float))).fillna(0).sum())
    source_head = reservoir_head + pump_gain

    aging_lookup = aging.set_index("pipe_id").to_dict("index")
    valve_lookup = valves.groupby("pipe_id")["minor_loss_k"].sum().to_dict() if not valves.empty else {}
    demand_lookup = nodes.set_index("node_id")["base_demand_lps"].to_dict()

    graph = nx.Graph()
    headloss_rows: list[dict[str, Any]] = []
    for _, pipe in pipes.iterrows():
        pipe_id = str(pipe["pipe_id"])
        score = float(aging_lookup.get(pipe_id, {}).get("aging_score", 0.0))
        diameter = max(float(pipe.get("diameter_mm", 250)), 50.0)
        length = max(float(pipe.get("length_m", 1)), 1.0)
        avg_demand = (
            float(demand_lookup.get(pipe.get("from_node"), 0.0))
            + float(demand_lookup.get(pipe.get("to_node"), 0.0))
        ) / 2
        valve_k = float(valve_lookup.get(pipe_id, 0.0))
        diameter_factor = (250.0 / diameter) ** 1.7
        gradient = (
            0.002
            + 0.050 * (score**1.8) * diameter_factor
            + 0.0015 * avg_demand
            + 0.0025 * float(pipe.get("repair_count", 0))
            + 0.0030 * float(pipe.get("leak_history_count", 0))
            + 0.0035 * valve_k
        )
        gradient = float(np.clip(gradient, 0.0005, 0.12))
        head_loss = gradient * length
        cause = "normal"
        if gradient >= HEAD_LOSS_GRADIENT_CRITICAL:
            cause = "aged rough pipe / bottleneck"
        elif gradient >= HEAD_LOSS_GRADIENT_WARNING:
            cause = "elevated aging, valve loss, or demand"
        headloss_rows.append(
            {
                "pipe_id": pipe_id,
                "from_node": pipe["from_node"],
                "to_node": pipe["to_node"],
                "head_loss_m": round(head_loss, 3),
                "head_loss_gradient": round(gradient, 5),
                "flow_lps": round(max(avg_demand * 3.0 + score * 4.0, 0.1), 3),
                "possible_cause": cause,
            }
        )
        graph.add_edge(str(pipe["from_node"]), str(pipe["to_node"]), weight=head_loss)

    path_loss = nx.single_source_dijkstra_path_length(graph, source_node, weight="weight")
    pressure_rows: list[dict[str, Any]] = []
    for _, node in nodes.iterrows():
        node_id = str(node["node_id"])
        elevation = float(node.get("elevation_m", 0.0))
        hydraulic_grade = source_head - float(path_loss.get(node_id, 0.0))
        pressure_head = hydraulic_grade - elevation
        pressure_rows.append(
            {
                "node_id": node_id,
                "node_type": node.get("node_type", "node"),
                "elevation_m": round(elevation, 2),
                "hydraulic_grade_m": round(hydraulic_grade, 2),
                "pressure_head_m": round(pressure_head, 2),
                "pressure_status": pressure_status(pressure_head),
                "base_demand_lps": node.get("base_demand_lps", 0.0),
            }
        )
    return pd.DataFrame(pressure_rows), pd.DataFrame(headloss_rows)


def normalize_pressure_results(node_results: pd.DataFrame) -> pd.DataFrame:
    pressure = node_results.copy()
    if "pressure_head_m" not in pressure.columns or "node_id" not in pressure.columns:
        return pd.DataFrame()
    pressure["pressure_status"] = pressure["pressure_head_m"].apply(pressure_status)
    keep = [
        col
        for col in [
            "node_id",
            "node_type",
            "elevation_m",
            "hydraulic_grade_m",
            "pressure_head_m",
            "pressure_status",
            "base_demand_lps",
            "is_pressure_compliant",
        ]
        if col in pressure.columns
    ]
    return pressure[keep].copy()


def normalize_headloss_results(pipe_results: pd.DataFrame) -> pd.DataFrame:
    headloss = pipe_results.copy()
    if "pipe_id" not in headloss.columns:
        return pd.DataFrame()
    if "head_loss_m" not in headloss.columns and "headloss_m" in headloss.columns:
        headloss["head_loss_m"] = headloss["headloss_m"]
    if "head_loss_gradient" not in headloss.columns:
        if "headloss_gradient_m_per_km" in headloss.columns:
            headloss["head_loss_gradient"] = headloss["headloss_gradient_m_per_km"] / 1000.0
        elif {"head_loss_m", "length_m"}.issubset(headloss.columns):
            headloss["head_loss_gradient"] = headloss["head_loss_m"].abs() / headloss["length_m"].clip(lower=1.0)
    if "head_loss_gradient" not in headloss.columns:
        return pd.DataFrame()
    if "flow_lps" not in headloss.columns:
        headloss["flow_lps"] = np.nan
    headloss["possible_cause"] = "normal"
    headloss.loc[headloss["head_loss_gradient"] >= HEAD_LOSS_GRADIENT_WARNING, "possible_cause"] = (
        "elevated aging, valve loss, or demand"
    )
    headloss.loc[headloss["head_loss_gradient"] >= HEAD_LOSS_GRADIENT_CRITICAL, "possible_cause"] = (
        "aged rough pipe / bottleneck"
    )
    keep = [
        col
        for col in [
            "pipe_id",
            "from_node",
            "to_node",
            "head_loss_m",
            "head_loss_gradient",
            "flow_lps",
            "possible_cause",
            "adjusted_roughness_c",
            "aging_score",
            "criticality_score",
        ]
        if col in headloss.columns
    ]
    return headloss[keep].copy()


def pressure_status(pressure_head_m: float) -> str:
    if pressure_head_m < MIN_PRESSURE_HEAD_M:
        return "low"
    if pressure_head_m < MARGINAL_PRESSURE_HEAD_M:
        return "marginal"
    if pressure_head_m > HIGH_PRESSURE_STRESS_M:
        return "high"
    return "ok"


def compute_recommendations(
    tables: dict[str, pd.DataFrame],
    aging: pd.DataFrame,
    pressure: pd.DataFrame,
    headloss: pd.DataFrame,
) -> pd.DataFrame:
    try:
        from aging_water_network.control.controller import rank_control_recommendations

        recommendations = rank_control_recommendations(tables=tables)
        rows = []
        for item in recommendations:
            if hasattr(item, "to_dict"):
                rows.append(item.to_dict())
            else:
                rows.append(asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item))
        if rows:
            frame = pd.DataFrame(rows)
            for col in ["affected_nodes", "affected_pipes", "risks"]:
                if col in frame.columns:
                    frame[col] = frame[col].apply(lambda value: ", ".join(value) if isinstance(value, list) else value)
            return frame.sort_values("score", ascending=False)
    except Exception:
        pass

    low_nodes = pressure.loc[pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M, "node_id"].astype(str).tolist()
    marginal_nodes = pressure.loc[
        pressure["pressure_head_m"].between(MIN_PRESSURE_HEAD_M, MARGINAL_PRESSURE_HEAD_M, inclusive="left"),
        "node_id",
    ].astype(str).tolist()
    aged_pipes = aging.loc[aging["aging_score"] >= 0.70, "pipe_id"].astype(str).tolist()
    severe_headloss = headloss.loc[
        headloss["head_loss_gradient"] >= HEAD_LOSS_GRADIENT_CRITICAL, "pipe_id"
    ].astype(str).tolist()
    max_aged_pressure = estimate_max_aged_pipe_pressure(tables["pipes"], pressure, aged_pipes)

    rows = []
    if low_nodes:
        rows.append(
            recommendation_row(
                "A1",
                "increase_pump_speed",
                "PU1",
                "Increase source pump head by a small step and re-check aged-pipe stress.",
                f"Targets {len(low_nodes)} low-pressure nodes below {MIN_PRESSURE_HEAD_M:.0f} m.",
                100 - 5 * len(low_nodes) - 0.4 * max_aged_pressure,
                affected_nodes=low_nodes,
                affected_pipes=aged_pipes,
                risks=["May increase leakage or burst exposure on high-aging pipes."],
            )
        )
    if severe_headloss:
        rows.append(
            recommendation_row(
                "A2",
                "dispatch_inspection",
                ", ".join(severe_headloss[:4]),
                "Inspect high-gradient pipe segments for roughness, partial valve closure, leak, or bottleneck.",
                f"Prioritizes {len(severe_headloss)} pipe segments above critical head-loss gradient.",
                92 - 2 * len(severe_headloss),
                affected_nodes=low_nodes + marginal_nodes,
                affected_pipes=severe_headloss,
                risks=["Field inspection does not immediately recover pressure."],
            )
        )
    if max_aged_pressure > HIGH_PRESSURE_STRESS_M and aged_pipes:
        rows.append(
            recommendation_row(
                "A3",
                "decrease_pump_speed",
                "PU1",
                "Reduce pressure exposure near aged source-side pipes while monitoring minimum service head.",
                f"Maximum estimated aged-pipe pressure exposure is {max_aged_pressure:.1f} m.",
                86 - 4 * len(low_nodes),
                affected_nodes=marginal_nodes,
                affected_pipes=aged_pipes,
                risks=["Can worsen marginal or low-pressure service areas."],
            )
        )
    if not rows:
        rows.append(
            recommendation_row(
                "A0",
                "no_action",
                None,
                "No control change is recommended under the current mock scenario.",
                "Pressure-head constraint is satisfied and no severe aged-pipe stress was detected.",
                100,
                affected_nodes=[],
                affected_pipes=[],
                risks=["Continue monitoring pressure sensors and aging indicators."],
            )
        )
    return pd.DataFrame(rows).sort_values("score", ascending=False)


def compute_dynamic_results(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    try:
        from aging_water_network.hydraulics.dynamic import run_dynamic_demand_simulation

        result = run_dynamic_demand_simulation(tables=tables, include_minor_losses=False)
        return {
            key: value
            for key, value in result.items()
            if isinstance(value, pd.DataFrame)
        }
    except Exception:
        return {
            "dynamic_summary": pd.DataFrame(),
            "node_time_results": pd.DataFrame(),
            "pipe_time_results": pd.DataFrame(),
            "node_demand_timeseries": pd.DataFrame(),
        }


def recommendation_row(
    action_id: str,
    action_type: str,
    target_id: str | None,
    description: str,
    expected_effect: str,
    score: float,
    affected_nodes: list[str],
    affected_pipes: list[str],
    risks: list[str],
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "action_type": action_type,
        "target_id": target_id or "",
        "description": description,
        "expected_effect": expected_effect,
        "score": round(float(score), 2),
        "affected_nodes": ", ".join(affected_nodes[:12]),
        "affected_pipes": ", ".join(affected_pipes[:12]),
        "risks": " ".join(risks),
    }


def estimate_max_aged_pipe_pressure(pipes: pd.DataFrame, pressure: pd.DataFrame, aged_pipes: list[str]) -> float:
    if not aged_pipes:
        return 0.0
    pressure_lookup = pressure.set_index("node_id")["pressure_head_m"].to_dict()
    values = []
    for _, pipe in pipes[pipes["pipe_id"].astype(str).isin(aged_pipes)].iterrows():
        values.append(
            np.nanmean(
                [
                    pressure_lookup.get(str(pipe["from_node"]), np.nan),
                    pressure_lookup.get(str(pipe["to_node"]), np.nan),
                ]
            )
        )
    return float(np.nanmax(values)) if values else 0.0


def render_overview(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    nodes = state.tables["nodes"]
    pipes = state.tables["pipes"]
    pressure = snapshot.pressure
    aging = snapshot.aging
    has_recommendation = not snapshot.recommendations.empty
    rec = snapshot.recommendations.iloc[0] if has_recommendation else pd.Series(dtype=object)

    low_count = int((pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M).sum())
    high_risk = int((aging["aging_score"] >= 0.70).sum())
    min_pressure = float(pressure["pressure_head_m"].min())

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Nodes", len(nodes))
    col2.metric("Pipes", len(pipes))
    col3.metric("Minimum pressure", f"{min_pressure:.1f} m")
    col4.metric("Low-pressure nodes", low_count)
    col5.metric("High-risk pipes", high_risk)

    st.subheader("Recommended action summary")
    if has_recommendation:
        preferred_cols = ["action_type", "target_id", "description", "expected_effect", "score"]
        visible_cols = [column for column in preferred_cols if column in rec.index]
        st.dataframe(
            pd.DataFrame([rec])[visible_cols],
            hide_index=True,
            use_container_width=True,
        )

    left, right = st.columns(2)
    with left:
        st.plotly_chart(create_pressure_bar(pressure, "Pressure status by node"), use_container_width=True)
    with right:
        st.plotly_chart(create_top_risk_bar(aging, top_n=8), use_container_width=True)


def render_network_map(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    selected_pipe = st.selectbox(
        "Inspect pipe",
        snapshot.aging.sort_values("aging_score", ascending=False)["pipe_id"].astype(str).tolist(),
    )
    st.plotly_chart(
        create_network_map(
            state.tables["nodes"],
            snapshot.tables["pipes"],
            aging=snapshot.aging,
            pressure=snapshot.pressure,
            valves=state.tables.get("valves"),
            pumps=state.tables.get("pumps"),
            leak_pipe_id=str(snapshot.leak_info.get("leak_pipe_id", "")),
            leak_node_id=str(snapshot.leak_info.get("leak_node_id", "")),
            suspect_pipes=_suspect_pipe_ids(snapshot.leak_candidates),
            low_pressure_nodes=snapshot.pressure.loc[
                snapshot.pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M, "node_id"
            ].astype(str).tolist(),
            title="Pipe aging and node pressure status",
        ),
        use_container_width=True,
    )
    pipe_detail = snapshot.aging[snapshot.aging["pipe_id"].astype(str) == selected_pipe]
    if not pipe_detail.empty:
        st.dataframe(
            pipe_detail.T.rename(columns={pipe_detail.index[0]: selected_pipe}).astype(str),
            use_container_width=True,
        )


def render_aging_model(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    left, right = st.columns(2)
    with left:
        st.plotly_chart(create_aging_distribution(snapshot.aging), use_container_width=True)
    with right:
        st.plotly_chart(create_material_summary(snapshot.aging), use_container_width=True)

    selected_pipe = st.selectbox(
        "Component breakdown pipe",
        snapshot.aging.sort_values("aging_score", ascending=False)["pipe_id"].astype(str).tolist(),
    )
    st.plotly_chart(create_component_breakdown(snapshot.aging, selected_pipe), use_container_width=True)
    st.dataframe(
        snapshot.aging.sort_values("aging_score", ascending=False).head(10),
        hide_index=True,
        use_container_width=True,
    )


def render_hydraulic_results(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    st.plotly_chart(create_pressure_bar(snapshot.pressure), use_container_width=True)
    st.plotly_chart(create_headloss_bar(snapshot.headloss), use_container_width=True)
    st.plotly_chart(
        create_pressure_timeseries(state.tables.get("sensors", pd.DataFrame()), state.tables.get("sensor_timeseries", pd.DataFrame())),
        use_container_width=True,
    )

    low_nodes = snapshot.pressure[snapshot.pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M]
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Pressure table")
        st.dataframe(snapshot.pressure.sort_values("pressure_head_m"), hide_index=True, use_container_width=True)
    with col2:
        st.subheader("Critical head-loss pipes")
        st.dataframe(
            snapshot.headloss.sort_values("head_loss_gradient", ascending=False),
            hide_index=True,
            use_container_width=True,
        )
    if not low_nodes.empty:
        st.warning(f"{len(low_nodes)} nodes are below the {MIN_PRESSURE_HEAD_M:.0f} m service constraint.")


def render_dynamic_demand(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    node_demand = state.node_demand_timeseries
    st.subheader("Current live step")
    current = pd.DataFrame([snapshot.summary])
    current.insert(0, "timestamp", snapshot.state.timestamp)
    current["total_demand_lps"] = round(float(snapshot.node_demands["demand_lps"].sum()), 4)
    st.dataframe(current, hide_index=True, use_container_width=True)

    if not node_demand.empty:
        node_pivot = node_demand.copy()
        node_pivot["timestamp"] = pd.to_datetime(node_pivot["timestamp"])
        top_nodes = (
            node_pivot.groupby("node_id")["demand_lps"]
            .max()
            .sort_values(ascending=False)
            .head(8)
            .index
        )
        st.subheader("Household-derived node demand traces")
        st.line_chart(
            node_pivot[node_pivot["node_id"].isin(top_nodes)]
            .pivot(index="timestamp", columns="node_id", values="demand_lps")
            .fillna(0.0),
            use_container_width=True,
        )

    st.subheader("Full-day hydraulic analysis")
    dynamic_key = live_state_cache_key(snapshot.state)
    if (
        "full_dynamic_result" in st.session_state
        and st.session_state.get("full_dynamic_key") != dynamic_key
    ):
        st.session_state.pop("full_dynamic_result", None)
        st.session_state.pop("full_dynamic_source", None)
        st.session_state.pop("full_dynamic_key", None)
    if st.button("전체 시간대 분석 실행", type="primary"):
        with st.spinner("96개 시간대 수리계산 중..."):
            st.session_state.full_dynamic_result = run_dynamic_demand_simulation(
                tables=snapshot.no_leak_tables,
                include_minor_losses=snapshot.state.include_minor_losses,
            )
            st.session_state.full_dynamic_key = dynamic_key
            st.session_state.full_dynamic_source = (
                "current pipe-aging edits and minor-loss setting; full-day base AMI demand without one-step leak/demand overrides"
            )
    result = st.session_state.get("full_dynamic_result")
    if not result:
        st.info("전체 96-step 분석은 앱 시작 시 자동 실행하지 않습니다. 버튼을 눌러 실행하세요.")
        return
    st.caption(st.session_state.get("full_dynamic_source", "full-day analysis"))

    summary = result["dynamic_summary"]
    chart = summary.copy()
    chart["timestamp"] = pd.to_datetime(chart["timestamp"])
    cols = st.columns(4)
    cols[0].metric("Peak demand", f"{summary['total_demand_lps'].max():.1f} L/s")
    cols[1].metric("Max pump gain", f"{summary['required_pump_head_gain_m'].max():.1f} m")
    cols[2].metric("Worst min pressure", f"{summary['min_pressure_head_m'].min():.1f} m")
    cols[3].metric("Out-of-bound steps", int((~summary["within_hydraulic_bounds"]).sum()))
    st.line_chart(
        chart.set_index("timestamp")[["total_demand_lps", "required_pump_head_gain_m"]],
        use_container_width=True,
    )
    st.dataframe(summary, hide_index=True, use_container_width=True)


def render_live_control(state: DashboardState) -> LiveSimulationSnapshot:
    node_demand = state.node_demand_timeseries
    if node_demand.empty:
        st.warning("Regenerate mock data to enable live demand control.")
        st.stop()

    st.subheader("Live pressure, demand, leak, and pipe-aging controls")
    timestamps = [
        pd.Timestamp(value)
        for value in sorted(pd.to_datetime(node_demand["timestamp"]).dropna().unique())
    ]
    st.session_state.live_timestamp = st.select_slider(
        "Time step",
        options=timestamps,
        value=pd.Timestamp(st.session_state.live_timestamp),
        format_func=lambda value: pd.Timestamp(value).strftime("%H:%M"),
    )

    controls = st.columns([1.0, 1.0, 1.15])
    with controls[0]:
        st.session_state.live_global_multiplier = st.slider(
            "전체 수요 배율",
            0.25,
            2.50,
            float(st.session_state.live_global_multiplier),
            0.05,
        )
        st.session_state.live_include_minor_losses = st.checkbox(
            "미세 손실수두 포함",
            value=bool(st.session_state.live_include_minor_losses),
        )
    with controls[1]:
        mode_label = st.radio(
            "압력 제어",
            ["자동 최소수두", "수동 공급수두"],
            index=0 if st.session_state.live_pressure_mode == "auto" else 1,
            horizontal=True,
        )
        st.session_state.live_pressure_mode = "auto" if mode_label == "자동 최소수두" else "manual"
        st.session_state.live_manual_source_head = st.slider(
            "수동 공급수두 (m)",
            35.0,
            110.0,
            float(st.session_state.live_manual_source_head),
            0.5,
        )
    with controls[2]:
        st.session_state.live_leak_enabled = st.checkbox(
            "누수 주입",
            value=bool(st.session_state.live_leak_enabled),
        )
        target_label = st.radio(
            "누수 위치 타입",
            ["pipe", "node"],
            index=0 if st.session_state.live_leak_target_type == "pipe" else 1,
            horizontal=True,
        )
        st.session_state.live_leak_target_type = target_label
        if target_label == "pipe":
            pipe_ids = state.tables["pipes"]["pipe_id"].astype(str).tolist()
            current = st.session_state.live_leak_target_id
            st.session_state.live_leak_target_id = st.selectbox(
                "누수 pipe",
                pipe_ids,
                index=pipe_ids.index(current) if current in pipe_ids else min(13, len(pipe_ids) - 1),
            )
        else:
            junctions = state.tables["nodes"].loc[
                state.tables["nodes"]["node_type"].astype(str).str.lower().eq("junction"), "node_id"
            ].astype(str).tolist()
            current = st.session_state.live_leak_target_id
            st.session_state.live_leak_target_id = st.selectbox(
                "누수 node",
                junctions,
                index=junctions.index(current) if current in junctions else min(15, len(junctions) - 1),
            )
        st.session_state.live_leak_demand_lps = st.slider(
            "누수량 (L/s)",
            0.0,
            8.0,
            float(st.session_state.live_leak_demand_lps),
            0.1,
        )

    demand_editor = render_demand_editor(state)
    render_pipe_editor(state)
    live_state = live_state_from_controls(state, demand_editor)

    t0 = time.perf_counter()
    snapshot = _compute_live_snapshot_cached(state.tables, state.node_demand_timeseries, live_state)
    snapshot = replace(snapshot, elapsed_ms=(time.perf_counter() - t0) * 1000.0)
    render_live_metrics(snapshot)
    render_live_map(state, snapshot)
    render_live_tables(snapshot)
    return snapshot


def render_demand_editor(state: DashboardState) -> pd.DataFrame:
    base_node_demand = (
        state.node_demand_timeseries[
            pd.to_datetime(state.node_demand_timeseries["timestamp"]).eq(
                pd.Timestamp(st.session_state.live_timestamp)
            )
        ][["node_id", "demand_lps"]]
        .copy()
    )
    editor = base_node_demand.merge(
        state.tables["nodes"][["node_id", "dma_id", "elevation_m"]],
        on="node_id",
        how="left",
    )
    editor["demand_multiplier"] = 1.0
    editor["extra_demand_lps"] = 0.0
    editor = editor[["node_id", "dma_id", "elevation_m", "demand_lps", "demand_multiplier", "extra_demand_lps"]]
    with st.expander("시간대별 지점 수요 직접 조절", expanded=False):
        return st.data_editor(
            editor,
            hide_index=True,
            use_container_width=True,
            column_config={
                "node_id": st.column_config.TextColumn("node_id", disabled=True),
                "dma_id": st.column_config.TextColumn("dma", disabled=True),
                "elevation_m": st.column_config.NumberColumn("elevation", disabled=True),
                "demand_lps": st.column_config.NumberColumn("base L/s", disabled=True, format="%.3f"),
                "demand_multiplier": st.column_config.NumberColumn("multiplier", min_value=0.0, max_value=5.0, step=0.05),
                "extra_demand_lps": st.column_config.NumberColumn("extra L/s", min_value=0.0, max_value=20.0, step=0.1),
            },
            key=f"live_demand_editor_{pd.Timestamp(st.session_state.live_timestamp).isoformat()}_{st.session_state.live_global_multiplier}",
        )


def render_pipe_editor(state: DashboardState) -> None:
    pipe_ids = state.tables["pipes"]["pipe_id"].astype(str).tolist()
    st.selectbox(
        "편집할 pipe",
        pipe_ids,
        index=pipe_ids.index(st.session_state.selected_pipe_id) if st.session_state.selected_pipe_id in pipe_ids else 0,
        key="selected_pipe_id",
    )
    selected = str(st.session_state.selected_pipe_id)
    base = state.tables["pipes"].loc[state.tables["pipes"]["pipe_id"].astype(str).eq(selected)].iloc[0]
    existing = st.session_state.live_pipe_overrides.get(selected, {})
    materials = ["cast_iron", "steel", "concrete", "ductile_iron", "PVC", "HDPE", "unknown"]

    cols = st.columns(6)
    material = cols[0].selectbox(
        "material",
        materials,
        index=materials.index(existing.get("material", base["material"])) if existing.get("material", base["material"]) in materials else 0,
        key=f"pipe_material_{selected}",
    )
    install_year = cols[1].number_input(
        "install year",
        min_value=1900,
        max_value=2026,
        value=int(existing.get("install_year", base["install_year"])),
        step=1,
        key=f"pipe_install_{selected}",
    )
    repair_count = cols[2].number_input(
        "repairs",
        min_value=0,
        max_value=20,
        value=int(existing.get("repair_count", base["repair_count"])),
        step=1,
        key=f"pipe_repairs_{selected}",
    )
    leak_history_count = cols[3].number_input(
        "leaks",
        min_value=0,
        max_value=20,
        value=int(existing.get("leak_history_count", base["leak_history_count"])),
        step=1,
        key=f"pipe_leaks_{selected}",
    )
    diameter_mm = cols[4].number_input(
        "diameter mm",
        min_value=50.0,
        max_value=1200.0,
        value=float(existing.get("diameter_mm", base["diameter_mm"])),
        step=10.0,
        key=f"pipe_diameter_{selected}",
    )
    override_enabled = cols[5].checkbox(
        "score override",
        value=existing.get("aging_score_override") is not None,
        key=f"pipe_override_on_{selected}",
    )
    aging_score_override = None
    if override_enabled:
        aging_score_override = st.slider(
            "manual aging score",
            0.0,
            1.0,
            float(existing.get("aging_score_override", 0.75)),
            0.01,
            key=f"pipe_aging_override_{selected}",
        )

    override = {
        "material": material,
        "install_year": int(install_year),
        "repair_count": int(repair_count),
        "leak_history_count": int(leak_history_count),
        "diameter_mm": float(diameter_mm),
        "aging_score_override": aging_score_override,
    }
    base_like = (
        material == base["material"]
        and int(install_year) == int(base["install_year"])
        and int(repair_count) == int(base["repair_count"])
        and int(leak_history_count) == int(base["leak_history_count"])
        and abs(float(diameter_mm) - float(base["diameter_mm"])) < 1e-9
        and aging_score_override is None
    )
    if base_like:
        st.session_state.live_pipe_overrides.pop(selected, None)
    else:
        st.session_state.live_pipe_overrides[selected] = override
    if st.button("선택 pipe 편집값 reset"):
        st.session_state.live_pipe_overrides.pop(selected, None)
        reset_pipe_widget_state(selected)
        st.rerun()


def render_live_metrics(snapshot: LiveSimulationSnapshot) -> None:
    metrics = st.columns(7)
    metrics[0].metric("총 수요", f"{snapshot.node_demands['demand_lps'].sum():.1f} L/s")
    metrics[1].metric("누수량", f"{float(snapshot.leak_info['leak_demand_lps']):.1f} L/s")
    metrics[2].metric("공급수두", f"{float(snapshot.summary['required_source_head_m']):.1f} m")
    metrics[3].metric("필요 펌프증가", f"{float(snapshot.summary['required_pump_head_gain_m']):.1f} m")
    metrics[4].metric("최소 수두", f"{float(snapshot.summary['min_pressure_head_m']):.1f} m")
    metrics[5].metric("저수두 노드", int(snapshot.summary["pressure_violations"]))
    metrics[6].metric("계산 시간", f"{snapshot.elapsed_ms:.0f} ms")
    if snapshot.summary["within_hydraulic_bounds"]:
        st.success("현재 조작값은 허용수두/고수두 범위 안에 있습니다.")
    else:
        st.error("현재 조작값은 수리학적 허용범위를 벗어납니다.")


def render_live_map(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    low_nodes = snapshot.pressure.loc[
        snapshot.pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M, "node_id"
    ].astype(str).tolist()
    suspect_pipes = _suspect_pipe_ids(snapshot.leak_candidates)
    fig = create_network_map(
        state.tables["nodes"],
        snapshot.tables["pipes"],
        aging=snapshot.aging,
        pressure=snapshot.pressure,
        valves=state.tables.get("valves"),
        pumps=state.tables.get("pumps"),
        leak_pipe_id=str(snapshot.leak_info.get("leak_pipe_id", "")),
        leak_node_id=str(snapshot.leak_info.get("leak_node_id", "")),
        suspect_pipes=suspect_pipes,
        low_pressure_nodes=low_nodes,
        selectable=True,
        title="Live controlled network state",
    )
    st.checkbox(
        "지도 클릭 편집 모드",
        value=bool(st.session_state.live_click_edit_mode),
        key="live_click_edit_mode",
        help="끄면 지도 렌더링이 더 안정적이고 빠릅니다. Pipe 편집은 아래 selectbox로 계속 가능합니다.",
    )
    if not st.session_state.live_click_edit_mode:
        st.plotly_chart(fig, use_container_width=True)
        st.caption("빠른 렌더 모드입니다. 클릭 편집이 필요하면 위 체크박스를 켜세요.")
        return

    if plotly_events is None:
        st.plotly_chart(fig, use_container_width=True)
        st.warning("streamlit-plotly-events is not installed, so map click selection is disabled.")
        return
    clicked = plotly_events(
        fig,
        click_event=True,
        hover_event=False,
        select_event=False,
        override_height=650,
        key="live_network_click",
    )
    parsed = parse_clicked_object(clicked, fig)
    if parsed:
        kind, item_id = parsed
        if kind == "pipe" and st.session_state.selected_pipe_id != item_id:
            st.session_state.selected_pipe_id = item_id
            st.rerun()
        if kind == "node" and st.session_state.selected_node_id != item_id:
            st.session_state.selected_node_id = item_id
            st.rerun()


def render_live_tables(snapshot: LiveSimulationSnapshot) -> None:
    left, right = st.columns(2)
    with left:
        st.subheader("Live pressure table")
        st.dataframe(snapshot.pressure.sort_values("pressure_head_m"), hide_index=True, use_container_width=True)
    with right:
        st.subheader("Leak recognition candidates")
        st.dataframe(snapshot.leak_candidates, hide_index=True, use_container_width=True)


def _suspect_pipe_ids(leak_candidates: pd.DataFrame, limit: int = 3) -> list[str]:
    if leak_candidates.empty or "pipe_id" not in leak_candidates.columns:
        return []
    candidates = leak_candidates.copy()
    if "is_injected_leak" in candidates.columns:
        candidates = candidates[~candidates["is_injected_leak"].astype(bool)]
    return candidates.head(limit)["pipe_id"].astype(str).tolist()


def render_control_recommendations(state: DashboardState, snapshot: LiveSimulationSnapshot) -> None:
    st.subheader("Ranked actions")
    recommendations = snapshot.recommendations.copy()
    if recommendations.empty:
        st.info("현재 live snapshot 기준으로 표시할 제어 권고가 없습니다.")
        return

    preferred_cols = [
        "action_type",
        "target_id",
        "description",
        "expected_effect",
        "score",
        "affected_nodes",
        "affected_pipes",
        "risks",
    ]
    visible_cols = [column for column in preferred_cols if column in recommendations.columns]
    st.dataframe(recommendations[visible_cols], hide_index=True, use_container_width=True)

    best = recommendations.iloc[0].to_dict()
    left, right = st.columns(2)
    with left:
        st.metric("Top action", best.get("action_type", "n/a"))
        st.metric("Action score", best.get("score", "n/a"))
        st.write(best.get("description", ""))
    with right:
        st.write("Expected effect")
        st.info(str(best.get("expected_effect", "")))
        st.write("Risks and trade-offs")
        st.warning(str(best.get("risks", "")))

    before_after = pd.DataFrame(
        [
            {
                "case": "Current live state",
                "source_head_m": f"{float(snapshot.summary.get('required_source_head_m', 0.0)):.2f}",
                "min_pressure_head_m": f"{float(snapshot.pressure['pressure_head_m'].min()):.2f}",
                "low_nodes": str(int((snapshot.pressure["pressure_head_m"] < MIN_PRESSURE_HEAD_M).sum())),
                "high_pressure_nodes": str(int((snapshot.pressure["pressure_head_m"] > HIGH_PRESSURE_STRESS_M).sum())),
            },
            {
                "case": "Top action estimate",
                "source_head_m": "set by action",
                "min_pressure_head_m": f"{estimate_after_action_min_pressure(snapshot.pressure, str(best.get('action_type', ''))):.2f}",
                "low_nodes": "re-run via Live Control",
                "high_pressure_nodes": "re-run via Live Control",
            },
        ]
    )
    st.subheader("Before / after estimate")
    st.dataframe(before_after, hide_index=True, use_container_width=True)


def estimate_after_action_min_pressure(pressure: pd.DataFrame, action_type: str) -> float:
    current = float(pressure["pressure_head_m"].min())
    if action_type == "increase_pump_speed":
        return round(current + 4.0, 2)
    if action_type == "decrease_pump_speed":
        return round(current - 3.0, 2)
    return round(current, 2)


if __name__ == "__main__":
    main()
