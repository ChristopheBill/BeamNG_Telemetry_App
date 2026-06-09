from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from math import cos, hypot, sin
from time import time
from typing import Any


@dataclass(slots=True)
class TelemetrySample:
    timestamp: float
    vehicle_id: str
    damage_pct: float | None
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
    raw_damage: dict[str, Any] = field(default_factory=dict)
    raw_state: dict[str, Any] = field(default_factory=dict)
    raw_electrics: dict[str, Any] = field(default_factory=dict)

    def to_export_record(self, elapsed_seconds: float | None = None) -> dict[str, Any]:
        timestamp = self.timestamp if elapsed_seconds is None else max(0.0, elapsed_seconds)
        record: dict[str, Any] = {
            "timestamp": round(timestamp, 2),
            "vehicle_id": self.vehicle_id,
            "position": list(self.position) if self.position is not None else None,
            "speed_kmh": round(self.speed_kph, 2) if self.speed_kph is not None else None,
            "rpm": int(round(self.rpm)) if self.rpm is not None else None,
            "gear": self.gear,
            "inputs": {
                "throttle": self.throttle,
                "brake": self.brake,
                "steering": self.steering,
            },
            "damage": self.damage_pct,
        }
        if self.fuel_pct is not None:
            record["fuel_pct"] = self.fuel_pct
        if self.engine_running is not None:
            record["engine_running"] = self.engine_running
        if self.raw_damage:
            record["contacts"] = _damage_contact_summary(self.raw_damage)
            record["damage_detail"] = self.raw_damage
        return record


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
            from beamngpy.sensors import Damage
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
            if "damage" not in vehicle.sensors:
                vehicle.sensors.attach("damage", Damage())
            if "electrics" not in vehicle.sensors:
                vehicle.sensors.attach("electrics", Electrics())

            vehicle.connect(bng)
            vehicle.sensors.poll()

            state = dict(vehicle.state)
            damage = dict(vehicle.sensors["damage"])
            electrics = dict(vehicle.sensors["electrics"])
            sample = self._build_sample(chosen_vehicle_id, state, electrics, damage)
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
        damage: dict[str, Any],
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
        damage_pct = _extract_damage_pct(damage)

        return TelemetrySample(
            timestamp=timestamp,
            vehicle_id=vehicle_id,
            damage_pct=damage_pct,
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
            raw_damage=damage,
            raw_state=state,
            raw_electrics=electrics,
        )


def export_sample_json(sample: TelemetrySample, output_dir: str | Path, elapsed_seconds: float | None = None) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = int(round(sample.timestamp * 1000))
    file_path = destination / f"{sample.vehicle_id}_{stamp}.json"
    payload = sample.to_export_record(elapsed_seconds=elapsed_seconds)
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return file_path


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
        damage_pct=0.02 + 0.01 * (0.5 + 0.5 * sin(phase * 0.8)),
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
        raw_damage={
            "damage": 0.02 + 0.01 * (0.5 + 0.5 * sin(phase * 0.8)),
            "part_damage": {"body": 0.02},
        },
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


def _extract_damage_pct(damage: dict[str, Any]) -> float | None:
    if not damage:
        return None

    for key in ("damage", "total_damage", "damage_total", "vehicle_damage"):
        value = _as_float(damage.get(key))
        if value is not None:
            return _normalize_ratio(value)

    part_damage = damage.get("part_damage")
    if isinstance(part_damage, dict) and part_damage:
        numeric = [_as_float(value) for value in part_damage.values()]
        values = [value for value in numeric if value is not None]
        if values:
            return _normalize_ratio(sum(values) / len(values))

    return None


def _normalize_ratio(value: float) -> float:
    if value < 0:
        return 0.0
    if value <= 1.0:
        return value
    if value <= 100.0:
        return min(value / 100.0, 1.0)
    return 1.0


def _damage_contact_summary(damage: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source": "damage_sensor",
        "damage_pct": _extract_damage_pct(damage),
    }
    part_damage = damage.get("part_damage")
    if isinstance(part_damage, dict) and part_damage:
        ranked_parts = sorted(
            (
                {"part": part, "damage": value}
                for part, value in ((part, _as_float(raw_value)) for part, raw_value in part_damage.items())
                if value is not None
            ),
            key=lambda item: item["damage"] or 0.0,
            reverse=True,
        )
        summary["part_damage"] = ranked_parts[:8]
    for key in ("collision_count", "contact_count", "contacts", "impacts"):
        if key in damage:
            summary[key] = damage[key]
    return summary