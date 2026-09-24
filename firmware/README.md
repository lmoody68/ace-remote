# A.C.E. Remote — ESP32 firmware (OBD-powered "one-plug" build)

The in-car device. It **plugs into the OBD-II port** for power, senses **engine-running** from that same
12 V line, reads **GPS**, and publishes to your A.C.E. Remote server over **secure cellular MQTT** — so theft
alerts + the live recovery map reach your phone even when you're miles away. It also drives a
**starter-interrupt relay** (the one hardwired piece) so **Immobilize/Kill** from your phone stops a thief
from cranking the car.

> This is a **reference sketch** — flash it and verify on hardware (Arduino can't be compiled here); the
> library APIs and logic are correct for the parts below.

## The design in one line
**One plug into the OBD-II port** (power + GPS + detection) **+ one relay** wired into the starter trigger
(the anti-theft muscle). No ignition-sense wire, no CAN transceiver required for the core features.

## Parts (bill of materials) — ~$60–90
| Part | ~Price | Why |
|---|---|---|
| **LILYGO T-SIM7000G** (ESP32 + SIM7000G) | $28–40 | brain + LTE-M/NB-IoT cellular + **GPS**, one board |
| **Data SIM** (Hologram, T-Mobile IoT…) | ~$2–5/mo | the cellular plan (tiny data use) |
| **LTE + GPS antennas** | incl. | usually bundled with the board |
| **12 V→5 V buck converter** (LM2596) | ~$8 | powers the ESP32 from the OBD 12 V |
| **OBD-II male connector / pigtail** | ~$10 | taps the OBD port pins (16, 4/5) cleanly |
| Resistors **100 kΩ + 22 kΩ** | ~$7 kit | voltage divider for engine-running sense |
| **12 V automotive relay + socket** (e.g. Bosch style) | ~$10 | the starter-interrupt immobilizer |
| **OBD-II splitter (optional)** | ~$12 | keep this device plugged in *and* still use your Veepeak |

## OBD-II port pinout (the pins we use)
Looking at the trapezoid connector: **Pin 16 = +12 V (constant)** · **Pins 4 & 5 = Ground** ·
(Pins 6 = CAN-H, 14 = CAN-L — only for the optional RPM upgrade).

## Wiring
**1. Power (from the OBD plug):**
`OBD pin 16 (+12 V) → buck converter IN+`, `OBD pin 4/5 (GND) → buck IN−`; buck `OUT` (5 V) → ESP32 5 V/GND.
> The OBD 12 V is **constant** (live even when the car is off), so the device stays awake and watching — which
> is what makes the theft alert possible.

**2. Engine-running sense (no extra wire — tap the same 12 V):**
`OBD +12 V → 100 kΩ → [node] → 22 kΩ → GND`, and `[node] → ESP32 GPIO 34`.
The alternator lifts the line to ~14 V when the engine runs (rests ~12.4 V parked). The firmware reads that
and reports `ignition on/off`. **Tune `RUNNING_VOLTS` in `config.h`** after watching the Serial Monitor.

**3. Starter-interrupt relay (the one hardwired piece — anti-theft muscle):**
- Find the **starter trigger wire** (the small wire that only carries 12 V *while cranking* — at the ignition
  switch or the starter solenoid's "S" terminal; verify with the Audi wiring diagram or a multimeter).
- **Cut it and route it through the relay's COMMON → NC (normally-closed) contacts.**
- `ESP32 GPIO 12 → relay module IN`; relay coil power from 12 V, ground to chassis.
- Result: relay **idle = starter works** (fail-safe — a dead device never locks *you* out); relay
  **energized = starter circuit open = thief can't crank it.**
> ✅ A **starter interrupt is inherently safe** — it can *never* stall a running engine, it only blocks
> cranking. That's why it's the right DIY choice. (Cutting a *running* engine's fuel/ignition is a different,
> pro-install job — not needed for real anti-theft.)
> ⚠️ Identifying the starter wire on a 2017 Audi Q7 is the one step to do carefully — take your time or have a
> shop do just this tap. Everything else is plug-in.

**4. Antennas:** connect LTE + GPS; put the **GPS antenna where it can see the sky** (top of dash / near a
window).

## Libraries & flashing
1. Arduino Library Manager: **TinyGSM**, **PubSubClient**, **ArduinoJson**. Board: **ESP32 Dev Module**.
2. Edit **`config.h`**: `VEHICLE_ID` (+ the two topics), your SIM `GSM_APN`, and your `MQTT_HOST/PORT/USER/PASS`
   (`MQTT_USE_TLS 1` on 8883). Set `KILL_RELAY_PIN`/`RELAY_ACTIVE_HIGH` to match your relay module.
3. Open `ace_remote_esp32.ino` → select board + port → **Upload**.
4. Serial Monitor (115200): modem restart → network → GPRS → GPS → `PUB ok {...}`. Start the engine — the line
   voltage climbs and the dashboard flips to **ENGINE ON**. Arm it, and the next start pages your phone.

## Broker (production)
Point it at a **private broker with TLS + auth**. Easiest for you: **run Mosquitto on your Proxmox** (a tiny
LXC behind your Cloudflare tunnel, or reachable over your LAN/VPN) with a username/password + a real cert.
Then set the same `mqtt` block in the server's `config.json`, `"enabled": true`, and a
`"command_topic": "ace-remote/<id>/command"` so **Kill/Immobilize** reach the device. (I can stand this up.)

## Behavior
- **Publish-on-change** — sends when ignition flips, the car moves past `MOVE_THRESHOLD_M`, or every
  `HEARTBEAT_MS`. Barely uses data, catches a theft instantly.
- **Remote command** — the device subscribes to `ace-remote/<id>/command` and acts on
  `{"action":"kill"|"immobilize"|"release"}` by engaging/releasing the starter relay. Boots **released**
  (fail-safe).
- Payload: `{vehicle_id, ignition, lat, lon, speed_mph, immobilized}` — exactly what the server's monitor
  expects.

## ⚠️ Battery drain (know this)
An OBD-powered device draws current 24/7. For a **daily-driven** car that's negligible. For **long storage**
(weeks parked), add a low-power sleep or just unplug it — or wire a small cutoff. (A future firmware rev can
deep-sleep the modem between checks to cut idle draw dramatically.)

## Optional upgrade — live RPM / coolant temp (OBD-II CAN)
The minimal build reports **ignition + GPS** (all theft/geofence/kill features need). To also show **RPM,
coolant, speed** on the dashboard, set `USE_OBD_CAN 1`, add an **SN65HVD230** CAN transceiver between the
ESP32 (`CAN_TX_PIN`/`CAN_RX_PIN`) and OBD pins **6 (CAN-H) / 14 (CAN-L)**, and query the standard PIDs
(request `7DF:[02 01 <PID>]`, read `7E8:[.. 41 <PID> data]`): `0x0C` RPM `=((A*256)+B)/4`, `0x05` coolant
`=A-40`, `0x0D` speed km/h `=A`. Add those fields to the JSON and the dashboard tiles fill in — no server
changes needed. (More involved + vehicle-CAN-dependent → next iteration.)
