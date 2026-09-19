/*
 * A.C.E. Remote — in-car firmware  (ESP32 + SIM7000G)
 * ----------------------------------------------------------------------------
 * Reads ignition (GPIO) + GPS (SIM7000G GNSS) and publishes telemetry to your
 * A.C.E. Remote server over SECURE CELLULAR MQTT, publish-on-change to save data.
 * The server turns "engine started while armed" / "moved while armed" into a
 * theft alert on your phone.
 *
 * Payload matches the server schema exactly:
 *   { "vehicle_id","ignition","lat","lon","speed_mph" }   (rpm/coolant optional — see README: CAN add-on)
 * Topic: ace-remote/<VEHICLE_ID>/telemetry
 *
 * Libraries (install via Arduino Library Manager):
 *   TinyGSM · PubSubClient · ArduinoJson · StreamDebugger(optional)
 * Board: "ESP32 Dev Module" (or your LilyGO T-SIM7000G profile).
 *
 * ⚠ POWER: wire the ESP32 to CONSTANT 12 V (through a buck converter), NOT just
 * OBD-port power that dies with the ignition — otherwise it can't detect an
 * unauthorized start while the car is "off," which is the whole point.
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

static double haversine_m(double aLat, double aLon, double bLat, double bLon) {
  const double R = 6371000.0, d2r = 0.017453292519943295;
  double dLat = (bLat - aLat) * d2r, dLon = (bLon - aLon) * d2r;
  double h = sin(dLat/2)*sin(dLat/2) + cos(aLat*d2r)*cos(bLat*d2r)*sin(dLon/2)*sin(dLon/2);
  return 2 * R * asin(fmin(1.0, sqrt(h)));
}

static void modemPowerOn() {
  pinMode(MODEM_PWRKEY, OUTPUT);
  digitalWrite(MODEM_PWRKEY, LOW);  delay(1000);   // T-SIM7000G: low pulse >1s powers the modem on
  digitalWrite(MODEM_PWRKEY, HIGH);
}

static bool mqttConnect() {
  Serial.print("MQTT connecting... ");
  bool ok = mqtt.connect(VEHICLE_ID, MQTT_USER, MQTT_PASS);
  Serial.println(ok ? "connected" : "failed");
  return ok;
}

void setup() {
  Serial.begin(115200);
  pinMode(IGNITION_PIN, INPUT);
  Serial.println("\nA.C.E. Remote device booting...");

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

  modem.enableGPS();                  // power up the GNSS engine
#if MQTT_USE_TLS
  // netClient.setInsecure();         // uncomment to skip cert validation while testing (NOT for production)
#endif
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqttConnect();
}

void publishTelemetry(int ign, bool fix, double lat, double lon, float speedMph) {
  StaticJsonDocument<256> doc;
  doc["vehicle_id"] = VEHICLE_ID;
  doc["ignition"]   = ign ? "on" : "off";
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
  mqtt.loop();

  int ign = digitalRead(IGNITION_PIN);              // HIGH = ignition on

  float lat = 0, lon = 0, spd = 0;                  // spd from modem is km/h
  bool fix = modem.getGPS(&lat, &lon, &spd);
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
