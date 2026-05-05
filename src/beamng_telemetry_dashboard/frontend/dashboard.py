from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from beamng_telemetry_dashboard.backend.telemetry import BeamNGTelemetryClient, build_demo_sample


def run_app() -> None:
    st.set_page_config(page_title="BeamNG Telemetry", page_icon="🚗", layout="wide")
    _inject_styles()

    st.markdown(
        """
        <div class="topline">
            <div>
                <p class="eyebrow">BeamNG.drive live telemetry</p>
                <h1>Minimal dashboard</h1>
                <p class="lede">A small monitor for vehicle speed, RPM, controls, and fuel. It auto-refreshes when live mode is on.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    settings = _render_sidebar()
    sample, vehicle_ids, source, error_message = _load_sample(settings)

    if error_message:
        st.warning(f"Live BeamNG read failed, showing demo data instead: {error_message}")

    _render_status_row(sample, source, settings, vehicle_ids)
    _render_metrics(sample)
    _render_body(sample, vehicle_ids, source, settings)


def _render_sidebar() -> dict[str, object]:
    with st.sidebar:
        st.caption("Setup")
        st.markdown(
            """
            1. Start BeamNG.drive.
            2. Load a scenario with a vehicle.
            3. Keep live mode enabled if you want auto polling.
            """
        )

        st.divider()
        st.subheader("Connection")
        host = st.text_input("Host", value=os.getenv("BEAMNG_HOST", "localhost"))
        port = st.number_input(
            "Port",
            min_value=1,
            max_value=65535,
            value=int(os.getenv("BEAMNG_PORT", "25252")),
            step=1,
        )
        home = st.text_input(
            "BeamNG home",
            value=os.getenv("BNG_HOME", ""),
            help="Optional. Set this when you want the app to launch BeamNG automatically.",
        )
        user = st.text_input(
            "BeamNG user",
            value=os.getenv("BNG_USER", ""),
            help="Optional user folder override.",
        )
        vehicle_id = st.text_input(
            "Vehicle id",
            value="",
            help="Leave blank to use the first active vehicle.",
        )
        use_live = st.checkbox("Live mode", value=True)
        launch = st.checkbox("Launch BeamNG if needed", value=False)
        auto_refresh = st.checkbox("Auto refresh", value=True)
        refresh_seconds = st.slider("Refresh interval", 1, 15, 3)

        if use_live and auto_refresh:
            st_autorefresh(interval=refresh_seconds * 1000, key="beamng-autorefresh")

        refresh_now = st.button("Refresh now", type="primary")

        st.divider()
        st.caption("Guide")
        st.write(
            "If the app shows demo data, check that BeamNG is open, a scenario is loaded, and the port matches the simulator connection."
        )

    return {
        "host": host,
        "port": int(port),
        "home": home.strip() or None,
        "user": user.strip() or None,
        "vehicle_id": vehicle_id.strip() or None,
        "use_live": use_live,
        "launch": launch,
        "refresh_now": refresh_now,
    }


def _load_sample(settings: dict[str, object]):
    if "history" not in st.session_state:
        st.session_state.history = []
    if "last_source" not in st.session_state:
        st.session_state.last_source = "demo"
    if "last_vehicle_ids" not in st.session_state:
        st.session_state.last_vehicle_ids = []

    client = BeamNGTelemetryClient(
        host=str(settings["host"]),
        port=int(settings["port"]),
        home=settings["home"],
        user=settings["user"],
    )

    source = "demo"
    vehicle_ids: list[str] = []
    error_message = None

    if settings["use_live"]:
        try:
            sample, vehicle_ids = client.read_sample(
                vehicle_id=settings["vehicle_id"],
                launch=bool(settings["launch"]),
            )
            source = "beamng"
        except Exception as exc:
            error_message = str(exc)
            sample = build_demo_sample()
    else:
        sample = build_demo_sample()

    st.session_state.last_source = source
    st.session_state.last_vehicle_ids = vehicle_ids
    st.session_state.history = [sample, *st.session_state.history][:119]

    return sample, vehicle_ids, source, error_message


def _render_status_row(sample, source: str, settings: dict[str, object], vehicle_ids: list[str]) -> None:
    status_class = "live" if source == "beamng" else "demo"
    status_text = "Live" if source == "beamng" else "Demo"
    refresh_mode = "Auto" if settings["use_live"] else "Manual"

    st.markdown(
        f"""
        <div class="status-row">
            <span class="pill {status_class}">{status_text}</span>
            <span class="subtle">{refresh_mode} polling</span>
            <span class="subtle">Vehicle: {sample.vehicle_id}</span>
            <span class="subtle">Vehicles found: {len(vehicle_ids) or 1}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metrics(sample) -> None:
    metrics = st.columns(4)
    metrics[0].metric("Speed", _format_value(sample.speed_kph, " km/h"))
    metrics[1].metric("RPM", _format_value(sample.rpm))
    metrics[2].metric("Throttle", _format_value(None if sample.throttle is None else sample.throttle * 100, "%"))
    metrics[3].metric("Brake", _format_value(None if sample.brake is None else sample.brake * 100, "%"))

    second = st.columns(4)
    second[0].metric("Steering", _format_value(sample.steering, " deg"))
    second[1].metric("Fuel", _format_value(sample.fuel_pct, "%"))
    second[2].metric("Gear", _format_value(sample.gear))
    second[3].metric("Engine", "On" if sample.engine_running else "Off")


def _render_body(sample, vehicle_ids: list[str], source: str, settings: dict[str, object]) -> None:
    left, right = st.columns([1.35, 0.9])
    with left:
        st.subheader("Trend")
        history_df = pd.DataFrame(
            [
                {
                    "time": item.timestamp,
                    "speed_kph": item.speed_kph,
                    "rpm": item.rpm,
                    "throttle_pct": None if item.throttle is None else item.throttle * 100,
                    "brake_pct": None if item.brake is None else item.brake * 100,
                }
                for item in [sample, *st.session_state.history][-120:]
            ]
        )
        if not history_df.empty:
            st.line_chart(history_df.set_index("time"))
        else:
            st.info("Waiting for the first sample.")

    with right:
        st.subheader("Setup")
        if source == "beamng":
            st.success("Connected to BeamNG.")
        else:
            st.info("Showing demo telemetry.")
        st.write(f"Vehicle id: {sample.vehicle_id}")
        if vehicle_ids:
            st.write("Active vehicles: " + ", ".join(vehicle_ids))
        if sample.position is not None:
            st.write("Position: " + ", ".join(f"{coord:,.2f}" for coord in sample.position))
        st.caption(f"Refresh: {'Auto' if settings['use_live'] else 'Manual'}")
        with st.expander("Raw payload", expanded=False):
            st.json({"state": sample.raw_state, "electrics": sample.raw_electrics})


def _format_value(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value}{suffix}"


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 1.5rem;
            max-width: 1180px;
        }
        .topline {
            padding: 1rem 1.1rem 1.1rem;
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 1rem;
            background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(246,248,251,0.96));
            margin-bottom: 0.8rem;
        }
        .eyebrow {
            margin: 0 0 0.2rem;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: rgba(71, 85, 105, 0.92);
        }
        .topline h1 {
            margin: 0;
            font-size: 2rem;
            line-height: 1.05;
            color: rgb(15, 23, 42);
        }
        .lede {
            margin: 0.4rem 0 0;
            max-width: 60ch;
            color: rgba(71, 85, 105, 0.98);
        }
        .status-row {
            display: flex;
            gap: 0.6rem;
            flex-wrap: wrap;
            align-items: center;
            margin: 0.4rem 0 0.9rem;
        }
        .pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.28rem 0.68rem;
            font-size: 0.78rem;
            font-weight: 600;
            border: 1px solid transparent;
        }
        .pill.live {
            background: rgba(16, 185, 129, 0.11);
            color: rgb(5, 150, 105);
            border-color: rgba(16, 185, 129, 0.18);
        }
        .pill.demo {
            background: rgba(100, 116, 139, 0.10);
            color: rgb(71, 85, 105);
            border-color: rgba(100, 116, 139, 0.16);
        }
        .subtle {
            color: rgb(100, 116, 139);
            font-size: 0.88rem;
        }
        section[data-testid="stSidebar"] {
            border-right: 1px solid rgba(15, 23, 42, 0.08);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )