# BeamNG Telemetry Dashboard

A small Streamlit app that reads vehicle telemetry from BeamNG.drive through BeamNGpy.

## What it shows

- Live or demo speed, RPM, throttle, brake, steering, fuel, and gear values
- Current vehicle position and raw BeamNG sensor payloads
- A compact trend chart for recent samples

## Requirements

- Python 3.10 or newer
- BeamNG.drive installed locally
- A running BeamNG scenario with at least one vehicle for live mode

## Install

```bash
pip install -e .
```

## Run

```bash
streamlit run app.py
```

## BeamNG setup

1. Start BeamNG.drive and load a scenario with a vehicle.
2. If you want the app to launch BeamNG automatically, set `BNG_HOME` to your BeamNG installation folder.
3. Adjust the host and port in the sidebar if your BeamNGpy connection uses something other than `localhost:25252`.
4. Click `Refresh telemetry` to read the current vehicle state.

## Notes

- If BeamNGpy cannot connect, the app falls back to a demo data feed so the UI still works.
- The app reads the active vehicle list from BeamNG and uses the first vehicle unless you type a specific vehicle id.
