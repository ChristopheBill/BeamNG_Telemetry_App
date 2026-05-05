from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, hypot, sin
from time import time
from typing import Any


@dataclass(slots=True)
class TelemetrySample:
    timestamp: float
    vehicle_id: str
    speed_mps: float | None
    speed_kph: float | None
    rpm: float | None
    throttle: float | None
    brake: float | None
    steering: float | None
    gear: int | None
    fuel_pct: float | None
    engine_running: bool | None
    position: tuple[float, float, float] | None
    raw_state: dict[str, Any] = field(default_factory=dict)
    raw_electrics: dict[str, Any] = field(default_factory=dict)


class BeamNGTelemetryClient:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 25252,
        home: str | None = None,
        user: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.home = home
        self.user = user

    def read_sample(
        self,
        vehicle_id: str | None = None,
        launch: bool = False,
    ) -> tuple[TelemetrySample, list[str]]:
        try:
            from beamngpy import BeamNGpy
            from beamngpy.sensors import Electrics
        except ImportError as exc:  # pragma: no cover - dependency missing in tests
            raise RuntimeError(
                "beamngpy is not installed. Install dependencies before connecting to BeamNG."
            ) from exc

        beamng = BeamNGpy(self.host, self.port, home=self.home, user=self.user)
        connected = beamng.open(launch=launch)
        bng = connected or beamng

        try:
            current_vehicles = bng.vehicles.get_current(include_config=False)
            vehicle_ids = sorted(current_vehicles.keys())
            if not vehicle_ids:
                raise RuntimeError(
                    "No vehicles are currently active in BeamNG. Load a scenario with a vehicle first."
                )

            chosen_vehicle_id = vehicle_id or vehicle_ids[0]
            if chosen_vehicle_id not in current_vehicles:
                raise RuntimeError(
                    f"Vehicle '{chosen_vehicle_id}' was not found. Available vehicles: {', '.join(vehicle_ids)}"
                )

            vehicle = current_vehicles[chosen_vehicle_id]
            if "electrics" not in vehicle.sensors:
                vehicle.sensors.attach("electrics", Electrics())

            vehicle.connect(bng)
            vehicle.sensors.poll()

            state = dict(vehicle.state)
            electrics = dict(vehicle.sensors["electrics"])
            sample = self._build_sample(chosen_vehicle_id, state, electrics)
            return sample, vehicle_ids
        finally:
            try:
                bng.disconnect()
            except Exception:
                pass

    @staticmethod
    def _build_sample(
        vehicle_id: str,
        state: dict[str, Any],
        electrics: dict[str, Any],
    ) -> TelemetrySample:
        timestamp = time()
        position = _vector3(state.get("pos"))
        velocity = _vector3(state.get("vel"))
        speed_from_state = _magnitude(velocity)

        speed_mps = _as_float(electrics.get("wheelspeed"))
        if speed_mps is None:
            speed_mps = speed_from_state
        speed_kph = speed_mps * 3.6 if speed_mps is not None else None

        rpm = _as_float(electrics.get("rpm"))
        throttle = _normalize_input(electrics.get("throttle_input"), electrics.get("throttle"))
        brake = _normalize_input(electrics.get("brake_input"), electrics.get("brake"))
        steering = _as_float(electrics.get("steering"))
        gear = _as_int(electrics.get("gear"), electrics.get("gear_index"), electrics.get("gear_m"))
        fuel_pct = _as_float(electrics.get("fuel"))
        engine_running = _as_bool(electrics.get("running"), electrics.get("ignition"))

        return TelemetrySample(
            timestamp=timestamp,
            vehicle_id=vehicle_id,
            speed_mps=speed_mps,
            speed_kph=speed_kph,
            rpm=rpm,
            throttle=throttle,
            brake=brake,
            steering=steering,
            gear=gear,
            fuel_pct=fuel_pct,
            engine_running=engine_running,
            position=position,
            raw_state=state,
            raw_electrics=electrics,
        )


def build_demo_sample(seed: float | None = None) -> TelemetrySample:
    now = time()
    phase = seed if seed is not None else now / 3.0
    speed_mps = 18.0 + 7.5 * sin(phase)
    rpm = 1600.0 + 800.0 * (0.5 + 0.5 * sin(phase * 1.2))
    throttle = 0.35 + 0.25 * (0.5 + 0.5 * sin(phase * 1.6))
    brake = 0.05 + 0.08 * (0.5 + 0.5 * cos(phase * 1.3))
    steering = 8.0 * sin(phase * 0.9)
    gear = 3 if speed_mps > 12 else 2
    fuel_pct = max(5.0, 72.0 - (phase % 40) * 0.5)
    position = (
        120.0 + 4.0 * cos(phase * 0.2),
        -35.0 + 2.5 * sin(phase * 0.25),
        1.4,
    )

    return TelemetrySample(
        timestamp=now,
        vehicle_id="demo_vehicle",
        speed_mps=speed_mps,
        speed_kph=speed_mps * 3.6,
        rpm=rpm,
        throttle=throttle,
        brake=brake,
        steering=steering,
        gear=gear,
        fuel_pct=fuel_pct,
        engine_running=True,
        position=position,
        raw_state={
            "pos": position,
            "vel": (speed_mps, 0.0, 0.0),
            "mode": "demo",
        },
        raw_electrics={
            "wheelspeed": speed_mps,
            "rpm": rpm,
            "throttle_input": throttle,
            "brake_input": brake,
            "steering": steering,
            "gear": gear,
            "fuel": fuel_pct,
            "running": True,
        },
    )


def _vector3(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def _magnitude(vector: tuple[float, float, float] | None) -> float | None:
    if vector is None:
        return None
    return hypot(hypot(vector[0], vector[1]), vector[2])


def _as_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _as_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            continue
    return None


def _normalize_input(primary: Any, fallback: Any) -> float | None:
    value = _as_float(primary, fallback)
    if value is None:
        return None
    if value > 1.0:
        return max(0.0, min(value / 100.0, 1.0))
    return max(0.0, min(value, 1.0))


def _as_bool(*values: Any) -> bool | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
    return None