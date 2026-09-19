// ─── A.C.E. Remote — ESP32 firmware config ───────────────────────────────────
// Copy nothing; just edit the values for your car + broker, then flash.
#pragma once

// ── Vehicle identity (must match the MQTT topic the server subscribes to) ──
#define VEHICLE_ID   "MY-CAR"
#define MQTT_TOPIC   "ace-remote/MY-CAR/telemetry"   // ace-remote/<VEHICLE_ID>/telemetry

// ── Cellular (SIM7000G) ──
#define GSM_APN      "hologram"        // your data-SIM APN (e.g. hologram, iot.tmobile, wholesale, super)
#define GSM_USER     ""
#define GSM_PASS     ""
#define GSM_PIN      ""                // SIM PIN, or "" if none

// ── MQTT broker (use TLS/8883 in production; your own broker + auth) ──
#define MQTT_HOST    "your-broker.example.com"
#define MQTT_PORT    8883              // 8883 = TLS. Use 1883 only for a throwaway test.
#define MQTT_USER    "ace-device"      // broker username ("" for none)
#define MQTT_PASS    "change-me"       // broker password
#define MQTT_USE_TLS 1                 // 1 = SSL (SIM7000 built-in), 0 = plaintext (test only)

// ── Reporting behavior (publish-on-change saves cellular data) ──
#define HEARTBEAT_MS      60000        // send a keep-alive at least this often, even if nothing changed
#define MOVE_THRESHOLD_M  25           // publish immediately if the car moves more than this many meters
#define POLL_MS           3000         // how often to read sensors/GPS while awake

// ── Ignition sensing ──
// Wire the ignition/ACC (switched 12 V) through a voltage divider (e.g. 100k/33k -> ~3 V) into this pin.
// HIGH = ignition on. The device MUST be powered from constant 12 V (see README) so it can still detect an
// unauthorized START while the car is "off" — that is the whole point of the theft alert.
#define IGNITION_PIN 34

// ── LilyGO T-SIM7000G board pins (change if you use a different board) ──
#define MODEM_TX     27
#define MODEM_RX     26
#define MODEM_PWRKEY 4
#define MODEM_DTR    25
#define MODEM_BAUD   115200
