"""GPU and CPU readings once a second while a local model runs.

Sensors come from the amdgpu and k10temp hwmon directories in sysfs. While
the GPU is idle it's runtime-suspended and its sensor files return EBUSY;
those readings are stored as NULL. Each sample is committed as it's taken, so
if the machine crashes mid-call the readings up to the crash survive.
"""
from __future__ import annotations

import glob
import os
import sqlite3
import threading
import time

from ai_delegator import db

SAMPLE_SECONDS = 1.0


def _hwmon(name: str) -> str | None:
    for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(d, "name")) as f:
                if f.read().strip() == name:
                    return d
        except OSError:
            continue
    return None


def _read(d: str | None, fname: str, scale: float) -> float | None:
    if d is None:
        return None
    try:
        with open(os.path.join(d, fname)) as f:
            return round(int(f.read().strip()) / scale, 1)
    except (OSError, ValueError):
        return None  # EBUSY while the GPU is asleep, or no such sensor


def sample(gpu: str | None, cpu: str | None) -> dict:
    return {
        "edge": _read(gpu, "temp1_input", 1000),
        "junction": _read(gpu, "temp2_input", 1000),
        "mem": _read(gpu, "temp3_input", 1000),
        "power": _read(gpu, "power1_average", 1_000_000),
        "sclk": _read(gpu, "freq1_input", 1_000_000),
        "fan_rpm": _read(gpu, "fan1_input", 1),
        "cpu": _read(cpu, "temp1_input", 1000),
    }


def sensors_found() -> dict:
    return {"gpu": _hwmon("amdgpu"), "cpu": _hwmon("k10temp")}


class Recorder:
    """Samples on a background thread for as long as the `with` block runs,
    then writes the peaks and averages onto the call's row."""

    def __init__(self, call_id: int):
        self.call_id = call_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Recorder":
        found = sensors_found()
        self._thread = threading.Thread(target=self._loop, args=(found["gpu"], found["cpu"]), daemon=True)
        self._thread.start()
        return self

    def _loop(self, gpu: str | None, cpu: str | None) -> None:
        conn = db.connect()
        start = time.monotonic()
        try:
            while True:
                s = sample(gpu, cpu)
                conn.execute(
                    "INSERT INTO gpu_samples (call_id, t, edge, junction, mem, power, sclk, fan_rpm, cpu) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (self.call_id, round(time.monotonic() - start, 1), s["edge"], s["junction"], s["mem"],
                     s["power"], s["sclk"], s["fan_rpm"], s["cpu"]),
                )
                conn.commit()
                if self._stop.wait(SAMPLE_SECONDS):
                    break
        except sqlite3.Error as e:
            print(f"GPU sampling for call {self.call_id} stopped: {e}", flush=True)
        finally:
            conn.close()

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        conn = db.connect()
        try:
            conn.execute("""
                UPDATE calls SET
                  gpu_peak_junction = (SELECT MAX(junction) FROM gpu_samples WHERE call_id = :id),
                  gpu_avg_junction  = (SELECT ROUND(AVG(junction), 1) FROM gpu_samples WHERE call_id = :id),
                  gpu_peak_edge     = (SELECT MAX(edge) FROM gpu_samples WHERE call_id = :id),
                  gpu_peak_mem      = (SELECT MAX(mem) FROM gpu_samples WHERE call_id = :id),
                  gpu_peak_power    = (SELECT MAX(power) FROM gpu_samples WHERE call_id = :id),
                  gpu_avg_power     = (SELECT ROUND(AVG(power), 1) FROM gpu_samples WHERE call_id = :id),
                  gpu_peak_fan      = (SELECT MAX(fan_rpm) FROM gpu_samples WHERE call_id = :id),
                  cpu_peak          = (SELECT MAX(cpu) FROM gpu_samples WHERE call_id = :id)
                WHERE id = :id
            """, {"id": self.call_id})
            conn.commit()
        finally:
            conn.close()
