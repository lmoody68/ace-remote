// ─── A.C.E. Remote — ESP32 firmware config  (OBD-powered "one-plug" build) ───
// Edit the values for your car + broker, then flash.  See ../README.md for wiring.
#pragma once

// ── Vehicle identity (must match the server's MQTT topics) ──
#define VEHICLE_ID          "MY-CAR"
#define MQTT_TOPIC          "ace-remote/MY-CAR/telemetry"   // device → server (this device publishes)
#define MQTT_COMMAND_TOPIC  "ace-remote/MY-CAR/command"     // server → device (kill / immobilize / release)

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

// ── Engine-running sense via the OBD-II 12 V line  (NO extra wire, NO CAN) ──
// The board is powered from the OBD-II port's CONSTANT 12 V pin (pin 16). Tap that SAME 12 V line through a
// divider — 100 kΩ (top) / 22 kΩ (bottom) → ~2.6 V at 14.4 V, safely under the 3.3 V ADC ceiling — into
// VBAT_SENSE_PIN. When the engine runs, the alternator lifts the line to ~13.8–14.6 V; parked it rests
// ~12.2–12.7 V. RUNNING_VOLTS is the threshold between them (read the Serial Monitor and tune per car).
#define VBAT_SENSE_PIN   34            // ADC1 pin reading the divided 12 V line
#define VBAT_DIVIDER     5.545f        // (100k+22k)/22k = 5.545 → converts ADC volts back to line volts
#define RUNNING_VOLTS    13.2f         // ≥ this = engine running (alternator charging)

// ── Starter-interrupt relay — the ONE hardwired piece (anti-theft muscle) ──
// Drive a 12 V automotive relay wired through the STARTER trigger wire on its COMMON→NC contacts, so:
//   relay OFF/idle  = NC closed = starter works normally  (fail-safe: a dead device still lets YOU start)
//   relay ON        = contact opens = starter circuit broken = thief can't crank it
// A starter interrupt is INHERENTLY SAFE — it can never stall a running engine, it only blocks CRANKING.
#define KILL_RELAY_PIN     12          // GPIO driving the relay module's IN pin
#define RELAY_ACTIVE_HIGH  1           // 1 = driving HIGH energizes/immobilizes; 0 = active-low module

// ── (Optional) OBD-II CAN for live RPM / coolant / speed — adds an SN65HVD230 transceiver ──
// Leave 0 for the minimal build: the voltage sense above already covers theft / geofence / kill.
#define USE_OBD_CAN   0
#define CAN_TX_PIN    21
#define CAN_RX_PIN    22

// ── LilyGO T-SIM7000G board pins (change if you use a different board) ──
#define MODEM_TX     27
#define MODEM_RX     26
#define MODEM_PWRKEY 4
#define MODEM_DTR    25
#define MODEM_BAUD   115200
