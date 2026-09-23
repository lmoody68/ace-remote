"""
A.C.E. Remote — live telematics + anti-theft server (FastAPI).

Device (real OBD/GPS or the simulator) → this server → your browser dashboard (WebSocket) and your phone
(push/SMS/email on theft, geofence, overheat, offline). Two ingest transports:
  • MQTT  (the real telematics path: device publishes ace-remote/<id>/telemetry; TLS + auth via config)
  • HTTP  POST /api/ingest  (zero-broker path for the software-first demo / simulator)

Run:  python -m backend.main   (or: uvicorn backend.main:app --port 8930)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
import urllib.request

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .monitor import Monitor, compass
from . import notify

_HERE = os.path.dirname(__file__)
_INDEX = os.path.join(_HERE, "..", "frontend", "index.html")

app = FastAPI(title="A.C.E. Remote")
# Allow A.C.E. Mobile (ace-auto.us) to POST live OBD reads to /api/ingest from the browser ("Guard mode").
app.add_middleware(CORSMiddleware,
                   allow_origins=["https://ace-auto.us", "https://www.ace-auto.us"],
                   allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
mon = Monitor()
_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


async def _broadcast(payload: dict) -> None:
    dead = []
    data = json.dumps(payload)
    for ws in list(_clients):
        try:
            await ws.send_text(data)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for d in dead:
        _clients.discard(d)


async def _process(reading: dict) -> None:
    """One telemetry reading → update state, push to dashboards, page the phone on real alerts."""
    fresh = mon.ingest(reading)
    await _broadcast(mon.snapshot())
    for a in fresh:
        res = await asyncio.to_thread(notify.send_alert, a)
        print(f"[alert] {a['level']}: {a['msg']}  -> {res}")


# ── HTTP ingest (simulator / demo) ───────────────────────────────────────────
@app.post("/api/ingest")
async def ingest(req: Request):
    try:
        await _process(await req.json())
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True}


@app.get("/api/state")
async def state():
    return mon.snapshot()


def _reverse_geocode(lat: float, lon: float) -> str | None:
    """Coords → street address (OpenStreetMap Nominatim, free, no key). Best-effort; returns None on failure."""
    try:
        url = (f"https://nominatim.openstreetmap.org/reverse?format=json&zoom=18&addressdetails=0"
               f"&lat={lat}&lon={lon}")
        req = urllib.request.Request(url, headers={"User-Agent": "ACE-Remote/1.0 (vehicle recovery)"})
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode()).get("display_name")
    except Exception:  # noqa: BLE001
        return None


@app.get("/api/le-report")
async def le_report():
    """🚓 Stolen-vehicle report for law enforcement: current location + street address, time & data-age,
    direction of travel, the full vehicle description, a Google Maps link, and the recent recovery trail."""
    s = mon.state
    v = notify.load_config().get("vehicle", {})
    vehicle = {"year": v.get("year", "2017"), "make": v.get("make", "Audi"),
               "model": v.get("model", "Q7 quattro Premium Plus 3.0T"),
               "color": v.get("color", ""), "plate": v.get("plate", ""),
               "plate_state": v.get("plate_state", ""), "vin": v.get("vin", "WA1LAAF70HD024141")}
    lat, lon, fix = s.get("lat"), s.get("lon"), None
    if lat is not None and lon is not None:
        addr = await asyncio.to_thread(_reverse_geocode, lat, lon)
        fix = {"lat": lat, "lon": lon, "ts": s.get("ts"),
               "age_secs": int(time.time() - (s.get("ts") or time.time())),
               "speed_mph": s.get("speed_mph"), "heading_deg": s.get("heading"),
               "heading": compass(s.get("heading")), "address": addr,
               "google_maps": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"}
    return {"vehicle": vehicle, "fix": fix, "armed": mon.armed,
            "immobilized": s.get("immobilized"), "online": s.get("online"),
            "trail": list(mon.track)[-100:], "generated": time.time()}


@app.post("/api/arm")
async def arm(req: Request):
    body = await req.json()
    mon.set_armed(bool(body.get("armed", True)))
    await _broadcast(mon.snapshot())
    return {"armed": mon.armed}


def _publish_command(action: str) -> None:
    """Best-effort: tell the REAL in-car device to act (kill/immobilize/release) over its MQTT command
    topic. No-op for the software-only demo (the Monitor already enforces the state)."""
    try:
        cfg = notify.load_config().get("mqtt", {})
        if not cfg.get("enabled"):
            return
        import paho.mqtt.publish as publish
        vid = mon.state.get("vehicle_id", "MY-CAR")
        publish.single(cfg.get("command_topic", f"ace-remote/{vid}/command"),
                       json.dumps({"action": action}),
                       hostname=cfg.get("host", "test.mosquitto.org"), port=int(cfg.get("port", 1883)),
                       auth=({"username": cfg["username"], "password": cfg.get("password", "")}
                             if cfg.get("username") else None),
                       tls={} if cfg.get("tls") else None)
    except Exception as e:  # noqa: BLE001
        print("[cmd] publish failed:", e)


async def _safe_body(req: Request) -> dict:
    try:
        return await req.json()
    except Exception:  # noqa: BLE001
        return {}


@app.post("/api/kill")
async def kill(req: Request):
    """🛑 Remote engine-cut (anti-theft). SAFETY: never cuts a MOVING engine — if the car is in motion it
    immobilizes it (blocks restart) and QUEUES the cut for the instant it stops. Needs {"confirm": true}."""
    if not (await _safe_body(req)).get("confirm"):
        return JSONResponse({"ok": False, "error": 'confirmation required — send {"confirm": true}'},
                            status_code=400)
    res = mon.request_kill()
    await asyncio.to_thread(_publish_command, "kill")
    await _broadcast(mon.snapshot())
    await asyncio.to_thread(notify.send_alert, {"ts": None, "level": "critical", "msg": res["msg"]}, None, True)
    return {"ok": True, **res}


@app.post("/api/immobilize")
async def immobilize(req: Request):
    """🔒 Block restart (safe anytime); cuts a stationary/idling engine. Needs {"confirm": true}."""
    if not (await _safe_body(req)).get("confirm"):
        return JSONResponse({"ok": False, "error": 'confirmation required — send {"confirm": true}'},
                            status_code=400)
    res = mon.immobilize()
    await asyncio.to_thread(_publish_command, "immobilize")
    await _broadcast(mon.snapshot())
    await asyncio.to_thread(notify.send_alert, {"ts": None, "level": "critical", "msg": res["msg"]}, None, True)
    return {"ok": True, **res}


@app.post("/api/release")
async def release():
    """✅ Owner re-enables the vehicle (clears immobilizer + any queued/active cut)."""
    res = mon.release()
    await asyncio.to_thread(_publish_command, "release")
    await _broadcast(mon.snapshot())
    return {"ok": True, **res}


@app.post("/api/test-alert")
async def test_alert():
    """Fire a test theft alert through the real notifier so you can confirm it reaches your phone."""
    a = {"ts": None, "level": "critical",
         "msg": "🚨 TEST: this is what a theft alert looks like on your phone. (A.C.E. Remote)"}
    res = await asyncio.to_thread(notify.send_alert, a, None, True)  # force = bypass level/cooldown
    return {"sent": res}


_DEMO_HOME = (38.7881, -90.4974)
_demo_running = False


async def _play_demo(scenario: str):
    """Server-side scenario player so the deployed URL is self-demonstrating (no local device needed)."""
    global _demo_running
    if _demo_running:
        return
    _demo_running = True
    try:
        h = _DEMO_HOME
        def rd(ign, rpm, temp=24, lat=h[0], lon=h[1], spd=0):
            return {"vehicle_id": "MY-CAR", "ignition": ign, "rpm": rpm, "coolant_temp_c": temp,
                    "lat": lat, "lon": lon, "speed_mph": spd}
        if scenario in ("theft", "drive"):
            mon.set_armed(True)
        await _process(rd("off", 0)); await asyncio.sleep(1.2)
        if scenario == "theft":
            for i in range(8):
                await _process(rd("on", random.randint(800, 1400), 26 + i)); await asyncio.sleep(1.1)
        elif scenario == "drive":
            await _process(rd("on", 900, 30)); await asyncio.sleep(1.1)
            for i in range(1, 9):
                await _process(rd("on", random.randint(1200, 2600), 30 + i,
                                   h[0] + 0.0009 * i, h[1] + 0.0009 * i, 15 + i * 3)); await asyncio.sleep(1.1)
        elif scenario == "overheat":
            mon.set_armed(False)
            for t in range(92, 120, 3):
                await _process(rd("on", random.randint(1500, 2500), t, spd=35)); await asyncio.sleep(1.1)
        else:  # normal
            mon.set_armed(False); await _process(rd("on", 850, 40)); await asyncio.sleep(1.1)
            for i in range(6):
                await _process(rd("on", random.randint(1300, 3000), 88,
                                   h[0] + 0.0002 * i, h[1] + 0.0002 * i, random.randint(20, 55))); await asyncio.sleep(1.1)
            await _process(rd("off", 0, 84))
    finally:
        _demo_running = False


@app.post("/api/demo")
async def demo(scenario: str = "theft"):
    asyncio.create_task(_play_demo(scenario))
    return {"playing": scenario}


@app.get("/health")
async def health():
    cfg = notify.load_config()
    return {"status": "ok", "service": "ace-remote", "armed": mon.armed,
            "online": mon.state["online"], "alerts_enabled": bool(cfg.get("enabled")),
            "channels": cfg.get("channels", [])}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    _clients.add(sock)
    try:
        await sock.send_text(json.dumps(mon.snapshot()))
        while True:
            await sock.receive_text()   # keepalive; dashboard doesn't send commands over WS
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(sock)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    try:
        return open(_INDEX, encoding="utf-8").read()
    except FileNotFoundError:
        return "<h1>A.C.E. Remote</h1><p>dashboard not found</p>"


# ── background: offline watchdog + optional MQTT subscriber ───────────────────
async def _offline_watch():
    while True:
        await asyncio.sleep(5)
        for a in mon.check_offline():
            await _broadcast(mon.snapshot())
            await asyncio.to_thread(notify.send_alert, a)


def _start_mqtt():
    """Subscribe to the device's telemetry topic if MQTT is configured. Publishes reach _process via the loop."""
    cfg = notify.load_config().get("mqtt", {})
    if not cfg.get("enabled"):
        return
    try:
        import paho.mqtt.client as mqtt
    except Exception:  # noqa: BLE001
        print("[mqtt] paho-mqtt not installed; skipping"); return

    topic = cfg.get("topic", "ace-remote/+/telemetry")

    def on_connect(c, *_):
        c.subscribe(topic); print(f"[mqtt] subscribed {topic}")

    def on_message(c, u, m):
        try:
            reading = json.loads(m.payload.decode())
            if _loop:
                asyncio.run_coroutine_threadsafe(_process(reading), _loop)
        except Exception as e:  # noqa: BLE001
            print("[mqtt] bad message:", e)

    c = mqtt.Client()
    if cfg.get("username"):
        c.username_pw_set(cfg["username"], cfg.get("password", ""))
    if cfg.get("tls"):
        c.tls_set()
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(cfg.get("host", "test.mosquitto.org"), int(cfg.get("port", 1883)), 60)
    c.loop_start()


@app.on_event("startup")
async def _startup():
    global _loop
    _loop = asyncio.get_running_loop()
    asyncio.create_task(_offline_watch())
    _start_mqtt()
    print("🚗 A.C.E. Remote up — dashboard http://127.0.0.1:8930  · ingest POST /api/ingest or MQTT")


def main():
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8930, log_level="warning")


if __name__ == "__main__":
    main()
