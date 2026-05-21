"""Serve the HTML dashboard and drawing-recognition API from Python."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from aging_water_network.control.controller import rank_control_recommendations  # noqa: E402
from aging_water_network.data.validators import REQUIRED_COLUMNS  # noqa: E402
from aging_water_network.hydraulics.source_pump_optimizer import predict_source_pump_operation  # noqa: E402
from aging_water_network.hydraulics.simulator import run_hydraulic_simulation  # noqa: E402


NUMERIC_COLUMN_DEFAULTS: dict[str, dict[str, float]] = {
    "nodes": {
        "x": 0.0,
        "y": 0.0,
        "elevation_m": 0.0,
        "base_demand_lps": 0.0,
    },
    "pipes": {
        "length_m": 100.0,
        "diameter_mm": 100.0,
        "install_year": 2015.0,
        "bend_count": 0.0,
        "valve_count": 0.0,
        "repair_count": 0.0,
        "leak_history_count": 0.0,
        "soil_ph": 7.0,
        "soil_resistivity_ohm_cm": 5000.0,
        "traffic_load_index": 1.0,
        "burst_history_count": 0.0,
    },
    "valves": {
        "operation_count_last_year": 0.0,
        "minor_loss_k": 0.0,
    },
    "pumps": {
        "base_head_gain_m": 0.0,
        "speed_multiplier": 1.0,
        "efficiency_percent": 65.0,
        "energy_price_per_kwh": 0.0,
    },
    "reservoirs": {
        "head_m": 50.0,
    },
    "tanks": {
        "min_level_m": 0.0,
        "max_level_m": 10.0,
        "initial_level_m": 5.0,
    },
    "sensors": {
        "noise_std": 0.0,
    },
    "sensor_timeseries": {
        "value": 0.0,
    },
    "demand_patterns": {
        "hour": 0.0,
        "step_index": 0.0,
        "multiplier": 1.0,
    },
    "energy_options": {
        "global_efficiency_percent": 65.0,
        "global_price_per_kwh": 0.0,
        "demand_charge": 0.0,
    },
    "pump_energy": {
        "efficiency_percent": 65.0,
        "energy_price_per_kwh": 0.0,
    },
    "households": {
        "occupants": 1.0,
        "base_demand_lps": 0.0,
        "peaking_factor": 1.0,
    },
    "household_demand_timeseries": {
        "demand_lps": 0.0,
    },
}


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "WaterNetworkDashboard/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib hook
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("access-control-allow-methods", "GET,HEAD,POST,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib hook
        route = unquote(urlparse(self.path).path)
        if route == "/api/health":
            self._send_json(_health_payload(), include_body=False)
            return
        self._serve_static(route, include_body=False)

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        route = unquote(urlparse(self.path).path)
        if route == "/api/health":
            self._send_json(_health_payload())
            return
        self._serve_static(route)

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        route = unquote(urlparse(self.path).path)
        if route != "/api/simulate-network":
            self.send_error(HTTPStatus.NOT_FOUND, "missing")
            return
        try:
            request = self._read_json_body()
            self._send_json(_simulate_network(request))
        except Exception as exc:  # pragma: no cover - runtime protection
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length > 30 * 1024 * 1024:
            raise ValueError("request body is too large")
        body = self.rfile.read(length).decode("utf-8")
        parsed = json.loads(body or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def _serve_static(self, route: str, *, include_body: bool = True) -> None:
        if route == "/":
            route = "/frontend/index.html"
        relative_path = Path(route.lstrip("/"))
        file_path = (REPO_ROOT / relative_path).resolve()
        if not file_path.is_file() or not _is_relative_to(file_path, REPO_ROOT):
            self.send_error(HTTPStatus.NOT_FOUND, "missing")
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "text/plain"
        if file_path.suffix.lower() in {".html", ".js", ".css", ".csv", ".json"}:
            content_type = f"{content_type};charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
        include_body: bool = True,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("content-type", "application/json;charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-private-network", "true")

def _health_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "drawing-recognition-api",
        "supports_cors": True,
    }


def _simulate_network(request: dict[str, Any]) -> dict[str, Any]:
    tables = _tables_from_request(request.get("tables") if isinstance(request.get("tables"), dict) else request)
    scenario = request.get("scenario") if isinstance(request.get("scenario"), dict) else {}
    source_head_m = _optional_float(scenario.get("source_head_m"))
    pump_head_m = _optional_float(scenario.get("pump_head_m"))
    demand_multiplier = float(scenario.get("demand_multiplier") or 1.0)

    if source_head_m is not None and not tables["reservoirs"].empty:
        tables["reservoirs"].loc[tables["reservoirs"].index[0], "head_m"] = source_head_m
    if pump_head_m is not None and not tables["pumps"].empty:
        active_index = tables["pumps"].index[0]
        tables["pumps"].loc[active_index, "base_head_gain_m"] = pump_head_m
        tables["pumps"].loc[active_index, "speed_multiplier"] = 1.0

    _apply_leaks_to_tables(tables, scenario.get("leaks") if isinstance(scenario.get("leaks"), list) else [])
    simulation = run_hydraulic_simulation(
        tables=tables,
        demand_multiplier=demand_multiplier,
        prefer_wntr=False,
    )
    recommendations = rank_control_recommendations(
        tables=tables,
        max_recommendations=5,
    )
    source_pump_prediction = predict_source_pump_operation(
        tables,
        demand_multiplier=demand_multiplier,
    )
    metadata = simulation.get("metadata", {})
    return {
        "engine": metadata.get("solver", "epanet_formula_fallback"),
        "hydraulic_formula": metadata.get("hydraulic_formula", "H-W"),
        "node_results": _records(simulation["node_results"]),
        "pipe_results": _records(simulation["pipe_results"]),
        "pressure_violations": _records(simulation.get("pressure_violations", pd.DataFrame())),
        "headloss_alerts": _records(simulation.get("headloss_alerts", pd.DataFrame())),
        "aged_pressure_stress": _records(simulation.get("aged_pressure_stress", pd.DataFrame())),
        "recommendations": [item.to_dict() for item in recommendations],
        "source_pump_prediction": source_pump_prediction,
        "summary": simulation.get("summary", {}),
        "warnings": ["EPANET 2.2 headloss equations are used in the local solver; the compiled EPANET Toolkit/GGA engine is not linked yet."],
    }


def _tables_from_request(payload: Any) -> dict[str, pd.DataFrame]:
    source = payload if isinstance(payload, dict) else {}
    tables = {
        "nodes": pd.DataFrame(source.get("nodes") or []),
        "pipes": pd.DataFrame(source.get("pipes") or []),
        "reservoirs": pd.DataFrame(source.get("reservoirs") or []),
        "pumps": pd.DataFrame(source.get("pumps") or []),
        "valves": pd.DataFrame(source.get("valves") or []),
        "options": pd.DataFrame(source.get("options") or []),
        "demand_patterns": pd.DataFrame(source.get("demand_patterns") or []),
        "energy_options": pd.DataFrame(source.get("energy_options") or []),
        "pump_energy": pd.DataFrame(source.get("pump_energy") or []),
    }
    for table_name, columns in REQUIRED_COLUMNS.items():
        if table_name not in tables:
            tables[table_name] = pd.DataFrame(columns=sorted(columns))
        else:
            for column in columns:
                if column not in tables[table_name].columns:
                    tables[table_name][column] = _default_column_value(table_name, column, len(tables[table_name]))
    _normalize_reservoir_ids(tables)
    _coerce_table_columns(tables)
    return tables


def _default_column_value(table_name: str, column: str, length: int) -> Any:
    if table_name == "reservoirs" and column == "reservoir_id":
        return ""
    if column in NUMERIC_COLUMN_DEFAULTS.get(table_name, {}):
        return NUMERIC_COLUMN_DEFAULTS[table_name][column]
    if table_name == "nodes" and column == "node_type":
        return "junction"
    if table_name == "nodes" and column == "dma_id":
        return "DMA-1"
    if table_name == "pipes" and column == "material":
        return "unknown"
    if column in {"status"}:
        return "on"
    if column in {"valve_type"}:
        return "isolation"
    return ""


def _normalize_reservoir_ids(tables: dict[str, pd.DataFrame]) -> None:
    reservoirs = tables.get("reservoirs")
    if reservoirs is None or reservoirs.empty:
        return
    if "reservoir_id" not in reservoirs.columns:
        reservoirs["reservoir_id"] = ""
    if "node_id" not in reservoirs.columns:
        reservoirs["node_id"] = ""
    missing = reservoirs["reservoir_id"].astype(str).isin({"", "nan", "None"})
    fallback_ids = []
    for index, reservoir in reservoirs.loc[missing].iterrows():
        node_id = str(reservoir.get("node_id") or "")
        fallback_ids.append(node_id if node_id and node_id not in {"nan", "None"} else f"RES_API_{index + 1}")
    reservoirs.loc[missing, "reservoir_id"] = fallback_ids


def _coerce_table_columns(tables: dict[str, pd.DataFrame]) -> None:
    for table_name, defaults in NUMERIC_COLUMN_DEFAULTS.items():
        frame = tables.get(table_name)
        if frame is None or frame.empty:
            continue
        for column, default in defaults.items():
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _apply_leaks_to_tables(tables: dict[str, pd.DataFrame], leaks: list[Any]) -> None:
    if tables["nodes"].empty or tables["pipes"].empty:
        return
    for leak in leaks:
        if not isinstance(leak, dict):
            continue
        pipe_id = str(leak.get("pipe_id") or "")
        demand = max(float(leak.get("demand_lps") or 0.0), 0.0)
        if not pipe_id or demand <= 0:
            continue
        match = tables["pipes"][tables["pipes"]["pipe_id"].astype(str).eq(pipe_id)]
        if match.empty:
            continue
        leak_node = str(match.iloc[0]["to_node"])
        mask = tables["nodes"]["node_id"].astype(str).eq(leak_node)
        tables["nodes"].loc[mask, "base_demand_lps"] = (
            pd.to_numeric(tables["nodes"].loc[mask, "base_demand_lps"], errors="coerce").fillna(0.0)
            + demand
        )


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def _records(frame: Any) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    records = frame.to_dict("records")
    return [
        {key: _json_value(value) for key, value in record.items()}
        for record in records
    ]


def _json_value(value: Any) -> Any:
    if isinstance(value, (list, dict, str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return None if pd.isna(value) else value
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardRequestHandler)
    print(f"Dashboard server running at http://{args.host}:{args.port}/frontend/index.html", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
