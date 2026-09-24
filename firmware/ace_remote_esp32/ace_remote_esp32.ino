/*
 * A.C.E. Remote — in-car firmware  (ESP32 + SIM7000G)  ·  OBD-POWERED "one-plug" build
 * ----------------------------------------------------------------------------
 * Powers from the OBD-II port's constant 12 V, senses "engine running" from that same 12 V line
 * (alternator raises it to ~14 V), reads GPS (SIM7000G GNSS), and publishes telemetry to your
 * A.C.E. Remote server over SECURE CELLULAR MQTT. The server turns "started while armed" / "moved
 * while armed" into a theft alert + live recovery map on your phone.
 *
 * It ALSO subscribes to the server's command topic and drives a STARTER-INTERRUPT relay — so
 * "Immobilize / Kill" from your phone opens the starter circuit and a thief can't crank the car.
 * (A starter interrupt is inherently safe: it never stalls a running engine, only blocks cranking.
 *  Fail-safe wiring: a dead device leaves the starter working so YOU are never locked out.)
 *
 * Publishes:  { vehicle_id, ignition, lat, lon, speed_mph, immobilized }   Topic: ace-remote/<id>/telemetry
 * Listens:    { "action": "kill" | "immobilize" | "release" }              Topic: ace-remote/<id>/command
 *
 * Libraries: TinyGSM · PubSubClient · ArduinoJson.   Board: "ESP32 Dev Module" / LilyGO T-SIM7000G.
 * Wiring + parts: see ../README.md.   (Reference sketch — flash & verify on hardware.)
 * ----------------------------------------------------------------------------
 */
#include "config.h"

#define TINY_GSM_MODEM_SIM7000
#define TINY_GSM_RX_BUFFER 1024
#include <TinyGsmClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <math.h>

HardwareSerial SerialAT(1);           // UART1 -> modem
TinyGsm        modem(SerialAT);
#if MQTT_USE_TLS
TinyGsmClientSecure netClient(modem); // SIM7000 built-in SSL
#else
TinyGsmClient  netClient(modem);
#endif
PubSubClient   mqtt(netClient);

// publish-on-change state
static int    lastIgnition = -1;
static double lastLat = 0, lastLon = 0;
static bool   haveFix = false;
static unsigned long lastPublish = 0;
static bool   immobilized = false;    // starter-interrupt relay engaged?

static double haversine_m(double aLat, double aLon, double bLat, double bLon) {
  const double R = 6371000.0, d2r = 0.017453292519943295;
  double dLat = (bLat - aLat) * d2r, dLon = (bLon - aLon) * d2r;
  double h = sin(dLat/2)*sin(dLat/2) + cos(aLat*d2r)*cos(bLat*d2r)*sin(dLon/2)*sin(dLon/2);
  return 2 * R * asin(fmin(1.0, sqrt(h)));
}

// ── starter-interrupt relay ────────────────────────────────────────────────
static void applyRelay() {
  // engaged (immobilized) => drive the relay's active level; idle => the opposite (starter works).
  bool level = immobilized ? (RELAY_ACTIVE_HIGH ? HIGH : LOW)
                           : (RELAY_ACTIVE_HIGH ? LOW  : HIGH);
  digitalWrite(KILL_RELAY_PIN, level);
}
static void setImmobilized(bool on) {
  immobilized = on;
  applyRelay();
  Serial.print("[relay] "); Serial.println(on ? "IMMOBILIZED — starter blocked" : "released — starter enabled");
}

// ── engine-running sense from the OBD 12 V line (alternator voltage) ────────
static float readLineVolts() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(VBAT_SENSE_PIN);   // calibrated ADC, averaged
  return (mv / 8.0f / 1000.0f) * VBAT_DIVIDER;
}

// ── incoming command from the server (kill / immobilize / release) ─────────
static void onCommand(char* topic, byte* payload, unsigned int len) {
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, payload, len)) return;
  const char* action = doc["action"] | "";
  Serial.print("[cmd] "); Serial.println(action);
  if (!strcmp(action, "kill") || !strcmp(action, "immobilize")) setImmobilized(true);
  else if (!strcmp(action, "release"))                          setImmobilized(false);
}

static bool mqttConnect() {
  Serial.print("MQTT connecting... ");
  bool ok = mqtt.connect(VEHICLE_ID, MQTT_USER, MQTT_PASS);
  Serial.println(ok ? "connected" : "failed");
  if (ok) mqtt.subscribe(MQTT_COMMAND_TOPIC);      // receive kill/immobilize/release from the server
  return ok;
}

static void modemPowerOn() {
  pinMode(MODEM_PWRKEY, OUTPUT);
  digitalWrite(MODEM_PWRKEY, LOW);  delay(1000);   // T-SIM7000G: low pulse >1s powers the modem on
  digitalWrite(MODEM_PWRKEY, HIGH);
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nA.C.E. Remote device booting (OBD-powered)...");

  pinMode(KILL_RELAY_PIN, OUTPUT);
  setImmobilized(false);                 // fail-safe: boot with the starter ENABLED
  analogReadResolution(12);
  analogSetPinAttenuation(VBAT_SENSE_PIN, ADC_11db);   // full ~0–3.3 V range on the sense pin

  modemPowerOn();
  SerialAT.begin(MODEM_BAUD, SERIAL_8N1, MODEM_RX, MODEM_TX);
  delay(3000);
  Serial.println("restarting modem...");
  modem.restart();
  if (strlen(GSM_PIN) && modem.getSimStatus() != 3) modem.simUnlock(GSM_PIN);

  Serial.print("waiting for network... ");
  if (!modem.waitForNetwork(60000L)) { Serial.println("no network — rebooting"); ESP.restart(); }
  Serial.println("ok");

  Serial.print("connecting GPRS ("); Serial.print(GSM_APN); Serial.print(")... ");
  if (!modem.gprsConnect(GSM_APN, GSM_USER, GSM_PASS)) { Serial.println("failed — rebooting"); ESP.restart(); }
  Serial.println("ok");

  modem.enableGPS();                     // power up the GNSS engine
#if MQTT_USE_TLS
  // netClient.setInsecure();            // uncomment to skip cert validation while testing (NOT production)
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setCallback(onCommand);
  mqttConnect();
}

void publishTelemetry(int ign, bool fix, double lat, double lon, float speedMph) {
  StaticJsonDocument<256> doc;
  doc["vehicle_id"]  = VEHICLE_ID;
  doc["ignition"]    = ign ? "on" : "off";
  doc["immobilized"] = immobilized;
  if (fix) { doc["lat"] = lat; doc["lon"] = lon; doc["speed_mph"] = (int)speedMph; }
  char buf[256];
  size_t n = serializeJson(doc, buf);
  bool ok = mqtt.publish(MQTT_TOPIC, (const uint8_t*)buf, n, false);
  Serial.print("PUB "); Serial.print(ok ? "ok  " : "ERR "); Serial.println(buf);
  lastPublish = millis();
}

void loop() {
  if (!modem.isGprsConnected()) { Serial.println("GPRS dropped — reconnecting"); modem.gprsConnect(GSM_APN, GSM_USER, GSM_PASS); }
  if (!mqtt.connected()) mqttConnect();
  mqtt.loop();                                        // service inbound commands

  float volts = readLineVolts();
  int   ign   = (volts >= RUNNING_VOLTS) ? 1 : 0;     // engine running = alternator charging the line

  float lat = 0, lon = 0, spd = 0;                    // spd from modem is km/h
  bool  fix = modem.getGPS(&lat, &lon, &spd);
  float speedMph = fix ? spd * 0.621371f : 0;

  // publish-on-change: ignition changed, moved past the threshold, or heartbeat elapsed
  bool ignitionChanged = (ign != lastIgnition);
  bool movedFar = (fix && haveFix && haversine_m(lastLat, lastLon, lat, lon) > MOVE_THRESHOLD_M);
  bool heartbeat = (millis() - lastPublish > HEARTBEAT_MS);

  if (ignitionChanged || movedFar || heartbeat) {
    if (mqtt.connected()) {
      publishTelemetry(ign, fix, lat, lon, speedMph);
      lastIgnition = ign;
      if (fix) { lastLat = lat; lastLon = lon; haveFix = true; }
    }
  }

  delay(POLL_MS);
}
