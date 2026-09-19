"""
A.C.E. Remote — the monitor brain.

Tracks a vehicle's live telematics (ignition, RPM, coolant temp, location, health), detects transitions,
and raises PHONE ALERTS for the events that matter to an owner:

  • THEFT (start-while-armed):  you parked, armed it, walked away — and the engine just STARTED.
  • THEFT/TOW (moved-while-armed): the car's GPS moved beyond your geofence while it's armed.
  • OVERHEAT: coolant temperature crossed a safe threshold.
  • OFFLINE: the monitor stopped reporting (unplugged / out of range / powered down).

Arming model (like a car alarm): ARM when you park; DISARM before you legitimately drive.
Pure logic, no I/O — the server layer turns a returned `alerts` payload into MQTT/WS/phone notifications.
"""
from __future__ import annotations

import math
import time
from collections import deque

RUNNING, OFF = "on", "off"


def _haversine_m(a_lat, a_lon, b_lat, b_lon) -> float:
    """Distance in meters between two lat/lon points."""
    if None in (a_lat, a_lon, b_lat, b_lon):
        return 0.0
    R = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = math.radians(b_lat - a_lat), math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


class Monitor:
    def __init__(self, offline_after: float = 25.0, armed: bool = True,
                 geofence_m: float = 60.0, overheat_c: float = 112.0):
        self.offline_after = offline_after
        self.geofence_m = geofence_m
        self.overheat_c = overheat_c
        self._armed = armed
        self._started_ts: float | None = None
        self._parked: tuple[float, float] | None = None
        self._last = {"theft": 0.0, "geo": 0.0, "overheat": 0.0}
        self.state = {
            "vehicle_id": "MY-CAR", "ignition": "unknown", "rpm": 0, "coolant_temp_c": None,
            "lat": None, "lon": None, "speed_mph": 0, "health": "unknown",
            "ts": 0.0, "online": False, "armed": armed, "running_secs": 0,
            "geofence_m": geofence_m,
        }
        self.history: deque = deque(maxlen=300)
        self.alerts: deque = deque(maxlen=100)

    # ── control ───────────────────────────────────────────────────────────────
    def set_armed(self, armed: bool) -> None:
        self._armed = bool(armed)
        self.state["armed"] = self._armed
        if armed and self.state["lat"] is not None:      # remember where it's parked when you arm it
            self._parked = (self.state["lat"], self.state["lon"])
        self._log("armed" if armed else "disarmed",
                  "🔒 Armed — theft protection ON" if armed else "🔓 Disarmed — safe to drive")

    @property
    def armed(self) -> bool:
        return self._armed

    # ── ingest one telemetry reading (real OBD/GPS or simulator) ───────────────
    def ingest(self, r: dict) -> list[dict]:
        """Update state from one reading; return a list of NEW alerts triggered by it (server pushes them)."""
        now = float(r.get("ts") or time.time())
        vid = str(r.get("vehicle_id") or self.state["vehicle_id"])
        rpm = int(r.get("rpm") or 0)
        temp = r.get("coolant_temp_c")
        lat, lon = r.get("lat"), r.get("lon")
        speed = int(r.get("speed_mph") or 0)
        ign = r.get("ignition")
        if ign not in (RUNNING, OFF):
            ign = RUNNING if rpm > 0 else OFF
        prev = self.state["ignition"]
        prev_parked = self._parked
        fresh: list[dict] = []

        # ── ignition transitions ──
        if prev in (None, "unknown", OFF) and ign == RUNNING:
            self._started_ts = now
            self._log("started", f"🚗 {vid} engine STARTED")
            if self._armed and now - self._last["theft"] > 15:
                self._last["theft"] = now
                fresh.append(self._alert("critical",
                    f"🚨 THEFT ALERT: {vid} just STARTED while ARMED and you didn't disarm it "
                    f"(RPM {rpm}). Someone may be stealing your car."))
        elif prev == RUNNING and ign == OFF:
            dur = int(now - (self._started_ts or now))
            self._log("stopped", f"🅿 {vid} engine OFF (ran {dur}s)")
            self._started_ts = None
            if lat is not None:
                self._parked = (lat, lon)      # remember where it came to rest

        # ── geofence: moved while armed ──
        if self._armed and prev_parked and lat is not None:
            moved = _haversine_m(prev_parked[0], prev_parked[1], lat, lon)
            if moved > self.geofence_m and now - self._last["geo"] > 20:
                self._last["geo"] = now
                fresh.append(self._alert("critical",
                    f"🚨 {vid} MOVED {int(moved)} m while ARMED — it may be driven off or towed."))

        # ── overheat ──
        if temp is not None and temp >= self.overheat_c and now - self._last["overheat"] > 60:
            self._last["overheat"] = now
            fresh.append(self._alert("warn", f"🔥 {vid} OVERHEATING: coolant {temp:.0f}°C."))

        health = "ok"
        if temp is not None and temp >= self.overheat_c:
            health = "overheat"
        if r.get("dtc"):
            health = "fault"

        self.state.update({
            "vehicle_id": vid, "ignition": ign, "rpm": rpm, "coolant_temp_c": temp,
            "lat": lat, "lon": lon, "speed_mph": speed, "health": health,
            "ts": now, "online": True, "armed": self._armed,
            "running_secs": int(now - self._started_ts) if (ign == RUNNING and self._started_ts) else 0,
        })
        return fresh

    # ── periodic offline check ─────────────────────────────────────────────────
    def check_offline(self) -> list[dict]:
        if self.state["online"] and self.state["ts"] and (time.time() - self.state["ts"] > self.offline_after):
            self.state["online"] = False
            return [self._alert("warn",
                "📵 Monitor offline — no heartbeat (unplugged, out of range, or powered down).")]
        return []

    # ── helpers ────────────────────────────────────────────────────────────────
    def _log(self, event: str, msg: str) -> None:
        self.history.appendleft({"ts": time.time(), "event": event, "msg": msg, "rpm": self.state.get("rpm", 0)})

    def _alert(self, level: str, msg: str) -> dict:
        a = {"ts": time.time(), "level": level, "msg": msg}
        self.alerts.appendleft(a)
        self._log("alert", msg)
        return a

    def snapshot(self) -> dict:
        return {"state": dict(self.state), "history": list(self.history)[:60], "alerts": list(self.alerts)[:30]}
