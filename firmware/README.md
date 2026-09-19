# A.C.E. Remote — ESP32 firmware

The in-car device. Reads **ignition + GPS** and publishes to your A.C.E. Remote server over **secure
cellular MQTT**, so the anti-theft alerts reach your phone even when you're miles away. This is a **reference
sketch** — flash it and verify on hardware (I can't compile Arduino here); the library APIs and logic are
correct for the parts below.

## Parts (bill of materials)
| Part | Why |
|---|---|
| **LilyGO T-SIM7000G** (ESP32 + SIM7000G) | the brain — ESP32 + LTE-M/NB-IoT cellular + **GPS**, one board |
| **Data SIM** (Hologram, T-Mobile IoT, etc.) | the cellular data plan (a few $/mo, tiny data use) |
| **LTE + GPS antennas** | included with most T-SIM7000G kits |
| **12 V → 5 V buck converter** (e.g. LM2596) | powers the ESP32 from the car battery |
| Resistors **100 kΩ + 33 kΩ** | voltage divider for the ignition sense |

## Wiring
1. **Power (constant 12 V):** tap a **constant** 12 V battery line → buck converter → 5 V into the ESP32.
   > ⚠️ **Do NOT power it only from the ignition/ACC or the OBD port.** If the device dies when the car
   > turns off, it can't detect an *unauthorized start* — which is the whole point of the theft alert.
   > (Add a small fuse; the device sips power, so battery drain is minimal.)
2. **Ignition sense:** tap the **switched** ignition/ACC 12 V wire → **100 kΩ** in series → node → **33 kΩ**
   to GND → node to **GPIO 34**. That divides ~12 V down to ~3 V (HIGH = ignition on).
3. **Antennas:** connect the **LTE** and **GPS** antennas; put the GPS antenna where it can see the sky.

## Libraries (Arduino Library Manager)
`TinyGSM` · `PubSubClient` · `ArduinoJson`. Board: **ESP32 Dev Module** (or a LilyGO T-SIM7000G profile).

## Configure & flash
1. Edit **`ace_remote_esp32/config.h`** — `VEHICLE_ID` + `MQTT_TOPIC` (must match the server's
   `ace-remote/<id>/telemetry`), your SIM `GSM_APN`, and your MQTT broker (`MQTT_HOST/PORT/USER/PASS`,
   `MQTT_USE_TLS 1` on **8883**).
2. Open `ace_remote_esp32.ino` in Arduino IDE / PlatformIO → select the board + port → **Upload**.
3. Open the Serial Monitor (115200). You should see: modem restart → network → GPRS → GPS → `PUB ok {...}`.
4. Turn the key: the dashboard flips to **ENGINE ON**; arm it and it'll page you on the next start.

## Broker (production)
Point it at a **private broker with TLS + auth** — e.g. a Mosquitto with a username/password and a Let's
Encrypt cert, or a hosted MQTT (HiveMQ Cloud free tier). Set the same `mqtt` block in the server's
`config.json` and `"enabled": true`. TLS cert validation on the SIM7000 is basic — for testing you can
`netClient.setInsecure()` (commented in the sketch), but use a real cert in production.

## Behavior
- **Publish-on-change** — it sends when ignition flips, when the car moves past `MOVE_THRESHOLD_M`, or every
  `HEARTBEAT_MS` — so it barely uses data yet catches a theft instantly.
- The payload is `{vehicle_id, ignition, lat, lon, speed_mph}`, exactly what the server's monitor expects.

## Optional upgrade — real RPM / coolant temp (OBD-II over CAN)
This sketch reports **ignition + GPS** (all the theft/geofence features need). To also show **live RPM,
coolant temp, and speed** on the dashboard, add a **CAN transceiver** (SN65HVD230) between the ESP32's
built-in TWAI/CAN controller and the OBD-II port's CAN pins (**6 = CAN-H, 14 = CAN-L**), then query the
standard PIDs — request `7DF: [02 01 <PID>]`, read `7E8: [.. 41 <PID> data]`:
- `0x0C` engine RPM = `((A*256)+B)/4`
- `0x05` coolant temp °C = `A - 40`
- `0x0D` vehicle speed km/h = `A`

Add those fields to the JSON (`rpm`, `coolant_temp_c`, `speed_mph`) and the dashboard tiles fill in — no
server changes needed. (That path is more involved and vehicle-CAN-dependent, so it's the next iteration.)
