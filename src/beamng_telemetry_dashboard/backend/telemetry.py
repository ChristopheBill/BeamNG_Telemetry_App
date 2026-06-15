from __future__ import annotations

import json
import logging
import re
import socket
import struct
from dataclasses import dataclass, field
from math import cos, hypot, sin
from pathlib import Path
from time import time
from typing import Any


logger = logging.getLogger(__name__)


_OUTGAUGE_BASE_STRUCT = struct.Struct("<I4sHBBfffffffIIfff16s16s")
_OUTGAUGE_WITH_ID_STRUCT = struct.Struct("<I4sHBBfffffffIIfff16s16si")


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
        host: str = "0.0.0.0",
        port: int = 4444,
        timeout_seconds: float = 5.0,
        home: str | None = None,
        user: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.home = home
        self.user = user

    def read_sample(
        self,
        vehicle_id: str | None = None,
        launch: bool = False,
    ) -> tuple[TelemetrySample, list[str]]:
        del launch

        packet = self._receive_packet()
        sample = self._build_sample(packet, vehicle_id=vehicle_id)
        return sample, [sample.vehicle_id]

    def _receive_packet(self) -> dict[str, Any]:
        bind_host = self.host or "0.0.0.0"
        timeout = max(0.1, float(self.timeout_seconds))

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass

            try:
                udp_socket.bind((bind_host, self.port))
            except OSError as exc:
                raise RuntimeError(
                    f"Unable to bind OutGauge listener to {bind_host}:{self.port}."
                ) from exc

            udp_socket.settimeout(timeout)

            while True:
                try:
                    payload, address = udp_socket.recvfrom(4096)
                except socket.timeout as exc:
                    raise RuntimeError(
                        f"No OutGauge UDP packet received on {bind_host}:{self.port} within {timeout:.1f} seconds. "
                        "Enable BeamNG.drive's OutGauge UDP protocol and point it at this listener."
                    ) from exc

                packet = _parse_outgauge_packet(payload, address)
                if packet is not None:
                    return packet

                logger.debug("Ignoring non-OutGauge UDP packet from %s:%s", address[0], address[1])

    @staticmethod
    def _build_sample(packet: dict[str, Any], vehicle_id: str | None = None) -> TelemetrySample:
        timestamp = time()
        label = vehicle_id or packet["vehicle_id"]

        return TelemetrySample(
            timestamp=timestamp,
            vehicle_id=label,
            damage_pct=None,
            speed_mps=packet["speed_mps"],
            speed_kph=packet["speed_kph"],
            rpm=packet["rpm"],
            throttle=packet["throttle"],
            brake=packet["brake"],
            steering=None,
            gear=packet["gear"],
            fuel_pct=packet["fuel_pct"],
            engine_running=packet["engine_running"],
            position=None,
            raw_damage={},
            raw_state=packet["raw_state"],
            raw_electrics=packet["raw_electrics"],
        )


def _parse_outgauge_packet(payload: bytes, address: tuple[str, int]) -> dict[str, Any] | None:
    if len(payload) not in {_OUTGAUGE_BASE_STRUCT.size, _OUTGAUGE_WITH_ID_STRUCT.size}:
        return None

    if len(payload) == _OUTGAUGE_WITH_ID_STRUCT.size:
        unpacked = _OUTGAUGE_WITH_ID_STRUCT.unpack(payload)
        (
            time_ms,
            car_raw,
            flags,
            gear,
            plid,
            speed_mps,
            rpm,
            turbo,
            eng_temp,
            fuel,
            oil_pressure,
            oil_temp,
            dash_lights,
            show_lights,
            throttle,
            brake,
            clutch,
            display1_raw,
            display2_raw,
            packet_id,
        ) = unpacked
    else:
        unpacked = _OUTGAUGE_BASE_STRUCT.unpack(payload)
        (
            time_ms,
            car_raw,
            flags,
            gear,
            plid,
            speed_mps,
            rpm,
            turbo,
            eng_temp,
            fuel,
            oil_pressure,
            oil_temp,
            dash_lights,
            show_lights,
            throttle,
            brake,
            clutch,
            display1_raw,
            display2_raw,
        ) = unpacked
        packet_id = None

    car = _decode_fixed_string(car_raw)
    if not car:
        car = "beam"
    if car.lower() != "beam":
        return None

    raw_state = {
        "protocol": "OutGauge",
        "time_ms": time_ms,
        "car": car,
        "flags": flags,
        "gear": gear,
        "plid": plid,
        "dash_lights": dash_lights,
        "show_lights": show_lights,
        "display1": _decode_fixed_string(display1_raw),
        "display2": _decode_fixed_string(display2_raw),
        "source_address": {"host": address[0], "port": address[1]},
    }
    raw_electrics = {
        "speed_mps": speed_mps,
        "rpm": rpm,
        "turbo_bar": turbo,
        "engine_temp_c": eng_temp,
        "fuel": fuel,
        "oil_pressure_bar": oil_pressure,
        "oil_temp_c": oil_temp,
        "throttle": _clamp_unit_interval(throttle),
        "brake": _clamp_unit_interval(brake),
        "clutch": _clamp_unit_interval(clutch),
        "id": packet_id,
    }

    vehicle_label = f"{car}_{packet_id}" if packet_id is not None else car

    return {
        "vehicle_id": _sanitize_filename_part(vehicle_label),
        "speed_mps": speed_mps,
        "speed_kph": speed_mps * 3.6,
        "rpm": rpm,
        "throttle": _clamp_unit_interval(throttle),
        "brake": _clamp_unit_interval(brake),
        "gear": _gear_from_outgauge(gear),
        "fuel_pct": fuel * 100.0 if fuel is not None and fuel <= 1.0 else fuel,
        "engine_running": rpm > 0.0,
        "raw_state": raw_state,
        "raw_electrics": raw_electrics,
    }


def export_sample_json(sample: TelemetrySample, output_dir: str | Path, elapsed_seconds: float | None = None) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = int(round(sample.timestamp * 1000))
    file_stem = _sanitize_filename_part(sample.vehicle_id)
    file_path = destination / f"{file_stem}_{stamp}.json"
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


def _decode_fixed_string(value: bytes) -> str:
    return value.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()


def _sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or "telemetry"


def _gear_from_outgauge(gear: int) -> int:
    return int(gear)


def _clamp_unit_interval(value: Any) -> float | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return max(0.0, min(numeric, 1.0))


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