from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from beamng_telemetry_dashboard import BeamNGTelemetryClient, build_demo_sample

st.set_page_config(page_title="BeamNG Telemetry", page_icon="🚗", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    .hero {
        padding: 1.2rem 1.4rem;
        border-radius: 1.25rem;
        background: linear-gradient(135deg, rgba(22,24,34,0.96), rgba(42,54,82,0.92));
        border: 1px solid rgba(255,255,255,0.08);
        color: white;
        box-shadow: 0 18px 60px rgba(0,0,0,0.18);
    }
    .hero h1 {
        margin: 0;
        font-size: 2.2rem;
        letter-spacing: -0.04em;
    }
    .hero p {
        margin: 0.35rem 0 0;
        color: rgba(255,255,255,0.82);
        font-size: 0.98rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1>BeamNG Telemetry Dashboard</h1>
        <p>Read live vehicle state from BeamNG.drive through BeamNGpy, or use the demo feed if BeamNG is not running.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Connection")
    host = st.text_input("Host", value=os.getenv("BEAMNG_HOST", "localhost"))
    port = st.number_input(
        "Port",
        min_value=1,
        max_value=65535,
        value=int(os.getenv("BEAMNG_PORT", "25252")),
        step=1,
    )
    home = st.text_input(
        "BeamNG home folder",
        value=os.getenv("BNG_HOME", ""),
        help="Optional. Set this when you want Streamlit to launch BeamNG automatically.",
    )
    user = st.text_input(
        "User folder",
        value=os.getenv("BNG_USER", ""),
        help="Optional BeamNG user folder override.",
    )
    launch = st.checkbox("Launch BeamNG if needed", value=False)
    vehicle_id = st.text_input(
        "Vehicle id",
        value="",
        help="Leave empty to use the first active vehicle in the current scenario.",
    )
    use_live = st.checkbox("Use BeamNG live data", value=True)
    refresh = st.button("Refresh telemetry", type="primary")


def format_value(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value}{suffix}"


if "history" not in st.session_state:
    st.session_state.history = []
if "last_source" not in st.session_state:
    st.session_state.last_source = "demo"
if "last_vehicle_ids" not in st.session_state:
    st.session_state.last_vehicle_ids = []

client = BeamNGTelemetryClient(
    host=host,
    port=int(port),
    home=home.strip() or None,
    user=user.strip() or None,
)

sample = None
source = "demo"
vehicle_ids: list[str] = []
error_message = None

if use_live:
    try:
        sample, vehicle_ids = client.read_sample(
            vehicle_id=vehicle_id.strip() or None,
            launch=launch,
        )
        source = "beamng"
    except Exception as exc:
        error_message = str(exc)
        sample = build_demo_sample()
else:
    sample = build_demo_sample()

st.session_state.last_source = source
st.session_state.last_vehicle_ids = vehicle_ids

if error_message:
    st.warning(f"Live BeamNG read failed, showing demo data instead: {error_message}")

st.subheader("Current Telemetry")
metrics = st.columns(5)
metrics[0].metric("Speed", format_value(sample.speed_kph, " km/h"))
metrics[1].metric("RPM", format_value(sample.rpm))
metrics[2].metric("Throttle", format_value(None if sample.throttle is None else sample.throttle * 100, "%"))
metrics[3].metric("Brake", format_value(None if sample.brake is None else sample.brake * 100, "%"))
metrics[4].metric("Gear", format_value(sample.gear))

second_row = st.columns(4)
second_row[0].metric("Steering", format_value(sample.steering, " deg"))
second_row[1].metric("Fuel", format_value(sample.fuel_pct, "%"))
second_row[2].metric("Engine running", "Yes" if sample.engine_running else "No")
second_row[3].metric("Source", source)

left, right = st.columns([1.2, 1])
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
                "gear": item.gear,
            }
            for item in [sample, *st.session_state.history][-120:]
        ]
    )
    if not history_df.empty:
        st.line_chart(history_df.set_index("time")[["speed_kph", "rpm", "throttle_pct", "brake_pct"]])
    else:
        st.info("No samples yet.")

with right:
    st.subheader("Vehicle Context")
    st.write(f"Vehicle id: {sample.vehicle_id}")
    if vehicle_ids:
        st.write("Active vehicles: " + ", ".join(vehicle_ids))
    if sample.position is not None:
        st.write(
            "Position: "
            + ", ".join(f"{coord:,.2f}" for coord in sample.position)
        )
    st.caption(f"Timestamp: {sample.timestamp:.2f}")
    with st.expander("Raw BeamNG data", expanded=False):
        st.json({"state": sample.raw_state, "electrics": sample.raw_electrics})

st.session_state.history = [sample, *st.session_state.history][:119]

st.divider()
st.write(
    "Run BeamNG.drive, load a scenario with a vehicle, then click Refresh telemetry. "
    "If BeamNGpy cannot connect, the dashboard stays usable with demo data."
)
