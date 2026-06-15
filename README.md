# BeamNG Telemetry Dashboard

A minimalist Streamlit dashboard that reads vehicle telemetry from BeamNG.drive through OutGauge UDP.

## Layout

- `src/beamng_telemetry_dashboard/backend/` contains the OutGauge listener and telemetry collection code.
- `src/beamng_telemetry_dashboard/frontend/` contains the Streamlit UI and auto-refresh logic.
- `app.py` is a thin launcher that starts the frontend.

## What it shows

- Live or demo speed, RPM, throttle, brake, steering, fuel, and gear values
- Current vehicle position and raw BeamNG sensor payloads
- Automatic polling at a configurable interval when live mode is enabled
- JSON snapshots written to disk for each live sample, using a schema close to:

```json
{
	"timestamp": 12.52,
	"vehicle_id": "car1",
	"position": [123.2, 54.1, 0.4],
	"speed_kmh": 78.4,
	"rpm": 3120,
	"gear": 3,
	"inputs": {
		"throttle": 0.63,
		"brake": 0.0,
		"steering": -0.12
	},
	"damage": 0.02
}
```
- A simple setup guide inside the UI

## Requirements

- Python 3.10 or newer
- BeamNG.drive installed locally
- OutGauge UDP enabled in BeamNG and pointed at the listener host/port

## Install

```bash
uv sync
```

If you prefer editable installs without `uv`, `pip install -e .` still works.

## Run

```bash
uv run streamlit run app.py
```

## BeamNG setup

1. Start BeamNG.drive and load a scenario.
2. Enable the OutGauge UDP protocol in BeamNG's protocol settings.
3. Use the sidebar to set the listener host and port, then point BeamNG at that address.
4. Enable live mode and choose an auto-refresh interval greater than zero.
5. Leave vehicle id empty unless you want a custom export label.

## Notes

- If no OutGauge packet arrives before the timeout, the app falls back to demo data so the UI remains usable.
- Live polling can be turned off entirely from the sidebar.
- The dashboard keeps a short history so the trend chart stays lightweight.
- The app writes one JSON file per live sample when export is enabled.
