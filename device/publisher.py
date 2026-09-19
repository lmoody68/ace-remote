#!/usr/bin/env python3
"""
A.C.E. Remote — device publisher.

Stands in for the in-car device (ESP32 + SIM7000G in production). Two modes:

  SIMULATOR (no hardware):
    python device/publisher.py --simulate normal     # a benign park→start→drive→stop cycle
    python device/publisher.py --simulate theft       # engine STARTS while you're away → theft alert
    python device/publisher.py --simulate drive        # car is driven off while armed → geofence alert
    python device/publisher.py --simulate overheat     # coolant climbs past the safe threshold

  REAL OBD-II DONGLE (your ELM327 — reuses A.C.E.'s approach; engine running = RPM>0):
    python device/publisher.py --obd                   # auto-scan, or --obd socket://192.168.0.10:35000

Transport: HTTP POST to the server by default (zero broker); add --mqtt to publish over MQTT instead.
"""
from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request

HOME = (38.7881, -90.4974)   # a St. Louis-area "parked" coordinate for the geofence demo


def _post(server: str, reading: dict) -> None:
    req = urllib.request.Request(server.rstrip("/") + "/api/ingest",
                                 data=json.dumps(reading).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=6).read()
    except Exception as e:  # noqa: BLE001
        print("  post failed:", e)


def _mqtt_pub(cfg: dict, vid: str, reading: dict):
    import paho.mqtt.publish as publish
    publish.single(cfg.get("topic", f"ace-remote/{vid}/telemetry"), json.dumps(reading),
                   hostname=cfg.get("host", "test.mosquitto.org"), port=int(cfg.get("port", 1883)),
                   auth=({"username": cfg["username"], "password": cfg.get("password", "")}
                         if cfg.get("username") else None),
                   tls={} if cfg.get("tls") else None)


def send(args, reading: dict):
    reading.setdefault("ts", time.time())
    print(f"  {reading['ignition']:>3}  rpm={reading['rpm']:>4}  "
          f"temp={reading.get('coolant_temp_c','-')}  ({reading.get('lat')},{reading.get('lon')})")
    if args.mqtt:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
        from notify import load_config
        _mqtt_pub(load_config().get("mqtt", {}), args.id, reading)
    else:
        _post(args.server, reading)


def _r(vid, ign, rpm, temp=None, lat=HOME[0], lon=HOME[1], speed=0):
    return {"vehicle_id": vid, "ignition": ign, "rpm": int(rpm), "coolant_temp_c": temp,
            "lat": lat, "lon": lon, "speed_mph": int(speed)}


def simulate(args):
    vid, sc = args.id, args.simulate
    print(f"SIMULATOR [{sc}] → {'MQTT' if args.mqtt else args.server}  (Ctrl+C to stop)\n")
    # everyone starts parked + off
    for _ in range(2):
        send(args, _r(vid, "off", 0, 24)); time.sleep(args.interval)

    if sc == "theft":
        print(">>> car is parked & (you should have it ARMED). Engine about to start WITHOUT you...\n")
        time.sleep(args.interval)
        for i in range(10):
            send(args, _r(vid, "on", random.randint(750, 1400), 26 + i)); time.sleep(args.interval)
    elif sc == "drive":
        print(">>> armed car is being driven off — location will breach the geofence...\n")
        send(args, _r(vid, "on", 900, 30)); time.sleep(args.interval)
        for i in range(1, 11):                      # walk the coordinate away from HOME
            send(args, _r(vid, "on", random.randint(1200, 2600), 30 + i,
                          HOME[0] + 0.0009 * i, HOME[1] + 0.0009 * i, speed=15 + i * 3))
            time.sleep(args.interval)
    elif sc == "overheat":
        for t in range(90, 122, 3):
            send(args, _r(vid, "on", random.randint(1500, 2500), t, speed=35)); time.sleep(args.interval)
    else:  # normal
        send(args, _r(vid, "on", 850, 40)); time.sleep(args.interval)         # start (idle)
        for i in range(8):                                                     # drive
            send(args, _r(vid, "on", random.randint(1300, 3000), 88 + random.randint(-3, 4),
                          HOME[0] + 0.0002 * i, HOME[1] + 0.0002 * i, speed=random.randint(20, 55)))
            time.sleep(args.interval)
        send(args, _r(vid, "off", 0, 84)); time.sleep(args.interval)          # park
    print("\nscenario complete.")


def read_obd(args):
    try:
        import obd
    except ImportError:
        print("python-OBD not installed. Run:  pip install obd    (then plug in your ELM327 dongle)")
        return
    conn = obd.OBD(args.obd if args.obd not in (None, "auto") else None)
    if not conn.is_connected():
        print("no OBD connection (dongle unplugged / ignition off / wrong port).")
        return
    print(f"OBD connected → {'MQTT' if args.mqtt else args.server}  (Ctrl+C to stop)\n")
    while True:
        rpm = conn.query(obd.commands.RPM)
        temp = conn.query(obd.commands.COOLANT_TEMP)
        speed = conn.query(obd.commands.SPEED)
        rpm_v = float(rpm.value.magnitude) if rpm and rpm.value is not None else 0
        temp_v = float(temp.value.magnitude) if temp and temp.value is not None else None
        spd_v = float(speed.value.magnitude) * 0.621 if speed and speed.value is not None else 0
        send(args, _r(args.id, "on" if rpm_v > 0 else "off", rpm_v, temp_v, None, None, spd_v))
        time.sleep(args.interval)


def main():
    ap = argparse.ArgumentParser(description="A.C.E. Remote device publisher")
    ap.add_argument("--simulate", nargs="?", const="normal",
                    choices=["normal", "theft", "drive", "overheat"])
    ap.add_argument("--obd", nargs="?", const="auto")
    ap.add_argument("--server", default="http://127.0.0.1:8930")
    ap.add_argument("--mqtt", action="store_true")
    ap.add_argument("--id", default="MY-CAR")
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args()
    try:
        if a.obd is not None:
            read_obd(a)
        else:
            a.simulate = a.simulate or "normal"
            simulate(a)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
