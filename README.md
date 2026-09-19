# 🚗 A.C.E. Remote — Live Telematics & Anti-Theft

Turn any car into a connected car. A.C.E. Remote streams a vehicle's **live status** to a web dashboard
and **pages your phone the moment something's wrong** — the engine starting while it's armed, the car being
driven off, overheating, or the monitor going dark. It's the remote/cloud sibling of **A.C.E.** (the
Automotive Cognitive Engine), which reads the same OBD-II data locally.

Built **software-first** — the whole stack runs today with a **device simulator**, no hardware required.
Plug in a real ELM327 OBD-II dongle and it reads your actual car; drop in an ESP32 + cellular modem and it
goes fully mobile.

## What it does
- **Live telematics** — ignition, RPM, coolant temp, speed, running time, health — updating in real time.
- **🚨 Theft alert to your phone** — you ARM it when you park; if the engine **starts while armed** (you
  didn't disarm it), you get an instant push/SMS: *"MY-CAR just STARTED while ARMED — someone may be
  stealing your car."*
- **📍 Geofence** — if the car **moves beyond your geofence while armed** (driven off or towed), you're paged.
- **🔥 Overheat** and **📵 offline** (lost heartbeat) alerts.
- **Web dashboard** — arm/disarm, live gauges, a geofence map, the alert feed, and a **"Test phone alert"**
  button.

## Run the demo (no hardware)
```bash
pip install -r requirements.txt
python -m backend.main                 # dashboard → http://127.0.0.1:8930
# in a second terminal, act like the car:
python device/publisher.py --simulate theft      # engine starts while armed → THEFT alert
python device/publisher.py --simulate drive       # driven off while armed → geofence alert
python device/publisher.py --simulate overheat    # coolant crosses the threshold
python device/publisher.py --simulate normal      # a benign park→drive→park cycle
```
Open the dashboard, hit **ARMED**, then run `--simulate theft` and watch the alert land.

## Use your real OBD-II dongle
```bash
pip install obd
python device/publisher.py --obd                  # auto-scan your ELM327 (engine running = RPM>0)
# or a WiFi/emulator adapter:  python device/publisher.py --obd socket://192.168.0.10:35000
```
The dongle provides RPM/temp/ignition; GPS (for geofence) comes from the in-car ESP32+cellular module in a
real deployment — the simulator provides it for the demo.

## Turn on phone alerts (off by default — safe)
Alerts are **dry-run** until you opt in. Edit `config.json`:
1. `"enabled": true`
2. **Push (recommended):** install the free **[ntfy](https://ntfy.sh)** app, subscribe to your `ntfy_topic`.
3. **SMS:** set your `phone` + `carrier` (uses the carrier's free email-to-SMS gateway — no Twilio).
4. Hit **Test phone alert** on the dashboard to confirm it reaches you.
`config.json` is gitignored (keeps your number/topic private); `config.example.json` is the template.

## Secure MQTT (the real telematics transport)
The demo uses HTTP for zero setup, but the device is built to publish over **MQTT** (as the ESP32 would).
Point it at your own broker in `config.json` → `mqtt` (host, TLS, username/password, per-device topic) and
set `"enabled": true`; run the publisher with `--mqtt`. The server subscribes and relays to the dashboard.

## Architecture
```
device (simulator / real OBD / ESP32+cellular)
   --HTTP or MQTT-->  backend (FastAPI): monitor brain + alert engine
                          |--- WebSocket --> web dashboard (live)
                          '--- push/SMS/email --> your phone (theft, geofence, overheat, offline)
```
- `backend/monitor.py` — state, transitions, theft/geofence/overheat/offline detection (pure logic, tested).
- `backend/notify.py` — phone dispatch: ntfy push · carrier-SMS · email (dry-run by default, cooldown).
- `backend/main.py` — FastAPI: HTTP+MQTT ingest, WebSocket, arm/disarm, test-alert, serves the dashboard.
- `device/publisher.py` — simulator scenarios + real ELM327 reader.
- `frontend/index.html` — the live dashboard (self-contained, no external deps).

## Honest limits / next steps
- The in-process state resets on restart (fine for one car; add a DB for a fleet).
- Real GPS/geofence needs the in-car cellular+GPS module; the OBD dongle alone has no location.
- Next: an ESP32 firmware sketch (cellular + secure MQTT + publish-on-change), trip history, and
  multi-vehicle accounts.
