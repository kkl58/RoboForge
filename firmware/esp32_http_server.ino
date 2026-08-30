/* RoboForge RHP1 HTTP firmware — ESP32 reference (v1)
 * WiFi robot body: the RoboForge brain (PC / Raspberry Pi) on the same
 * network drives it over REST, exactly as in firmware/PROTOCOL.md.
 * Set WiFi credentials, flash, then:
 *   python main.py --chat --backend http --base-url http://<esp32-ip>
 */

#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";

WebServer server(80);
float cmd_v = 0, cmd_w_deg = 0;          // latched setpoints
unsigned long last_cmd_ms = 0;

// ---- replace with your chassis (same hooks as the serial firmware) ----
void driveWheels(float v_l, float v_r) { (void)v_l; (void)v_r; }
void readOdometry(float* x, float* y, float* th) {
  static float px = 0, py = 0, pth = 0; static unsigned long t0 = millis();
  float dt = (millis() - t0) / 1000.0f; t0 = millis();
  px += cmd_v * cosf(pth) * dt; py += cmd_v * sinf(pth) * dt;
  pth += radians(cmd_w_deg) * dt;
  *x = px; *y = py; *th = degrees(pth);
}
// -----------------------------------------------------------------------

void sendOk(JsonDocument& extra) {
  StaticJsonDocument<512> r; r["ok"] = true;
  for (JsonPair kv : extra.as<JsonObject>()) r[kv.key()] = kv.value();
  server.send(200, "application/json");
  String out; serializeJson(r, out); server.sendContent(out);
}

void setupRoutes() {
  server.on("/ping", HTTP_GET, [] {
    StaticJsonDocument<128> r; r["pong"] = "RHP1"; sendOk(r);
  });
  server.on("/pose", HTTP_GET, [] {
    float x, y, th; readOdometry(&x, &y, &th);
    StaticJsonDocument<256> r;
    JsonObject p = r.createNestedObject("pose");
    p["x"] = x; p["y"] = y; p["theta_deg"] = th;
    sendOk(r);
  });
  server.on("/vel", HTTP_POST, [] {
    StaticJsonDocument<128> doc;
    deserializeJson(doc, server.arg("plain"));
    cmd_v = constrain((float)(doc["l"] | 0.0f), -1.5f, 1.5f);
    cmd_w_deg = constrain((float)(doc["a"] | 0.0f), -60.0f, 60.0f);
    last_cmd_ms = millis();
    StaticJsonDocument<64> r; sendOk(r);
  });
  server.on("/stop", HTTP_POST, [] {
    cmd_v = 0; cmd_w_deg = 0;
    StaticJsonDocument<64> r; sendOk(r);
  });
  server.on("/grab", HTTP_POST, [] {
    StaticJsonDocument<64> r; r["grabbed"] = true; sendOk(r); // wire your gripper
  });
  server.on("/release", HTTP_POST, [] { StaticJsonDocument<64> r; sendOk(r); });
  server.on("/carrying", HTTP_GET, [] {
    StaticJsonDocument<64> r; r["carrying"] = nullptr; sendOk(r);
  });
  server.on("/objects", HTTP_GET, [] {
    StaticJsonDocument<256> r; r["objects"] = JsonArray(); sendOk(r);
  });
}

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(200); digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN)); }
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.print("RoboForge body at http://");
  Serial.println(WiFi.localIP());
  setupRoutes();
  server.begin();
}

void loop() {
  server.handleClient();
  if (millis() - last_cmd_ms > 500) { cmd_v = 0; cmd_w_deg = 0; }  // watchdog
  float w = radians(cmd_w_deg);
  driveWheels(cmd_v - w * 0.10f, cmd_v + w * 0.10f);  // track = 0.20 m
  delay(10);
}
