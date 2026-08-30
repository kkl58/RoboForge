// RoboForge RHP1 serial firmware — Arduino / ESP32 reference (v1)
// Implements firmware/PROTOCOL.md over USB-serial at 115200 8N1.
// Differential drive: v_l = v - w*track/2, v_r = v + w*track/2 (rad/s on MCU).
//
// This is REFERENCE firmware: adapt pin mapping, encoders and e-stop to
// your chassis. The control loop, ramping and watchdog below are the part
// that matters for protocol conformance.

#include <ArduinoJson.h>   // by Benoit Blanchon, install from Library Manager

const float WHEEL_TRACK_M = 0.20;
const float MAX_V = 1.5;         // m/s — matches the PC-side safety layer
const float MAX_W_DEG = 60.0;    // deg/s
const unsigned long WATCHDOG_MS = 500;

float cmd_v = 0, cmd_w_deg = 0;  // latched setpoints from the PC
unsigned long last_cmd_ms = 0;

// ---- replace with your chassis drivers ----
void driveWheels(float v_l, float v_r) {
  // analogWrite(LEFT_PIN,  ...); analogWrite(RIGHT_PIN, ...);
  (void)v_l; (void)v_r;
}
void gripper(bool close, const char* name) { (void)close; (void)name; }
void readOdometry(float* x, float* y, float* th_deg) {
  // wheel encoders -> pose. Placeholder returns a tiny drift for demo.
  static float px = 0, py = 0, pth = 0;
  static unsigned long t0 = millis();
  float dt = (millis() - t0) / 1000.0; t0 = millis();
  float w = radians(cmd_w_deg);
  px += cmd_v * cos(pth) * dt;  py += cmd_v * sin(pth) * dt;
  pth += w * dt;
  *x = px; *y = py; *th_deg = degrees(pth);
}
// --------------------------------------------

void send(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void applyRamped(float target_v, float target_w) {
  // ramp limiting: never jump to full throttle (per PROTOCOL.md)
  static float cur_v = 0, cur_w = 0;
  cur_v += constrain(target_v - cur_v, -0.5f, 0.5f);
  cur_w += constrain(target_w - cur_w, -30.0f, 30.0f);
  float w_rad = radians(cur_w);
  driveWheels(cur_v - w_rad * WHEEL_TRACK_M / 2, cur_v + w_rad * WHEEL_TRACK_M / 2);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  // watchdog: no message from the brain for 500 ms -> stop
  if (millis() - last_cmd_ms > WATCHDOG_MS) { cmd_v = 0; cmd_w_deg = 0; }

  if (Serial.available()) {
    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, Serial) == DeserializationError::Ok && doc["cmd"]) {
      last_cmd_ms = millis();
      const char* cmd = doc["cmd"];

      StaticJsonDocument<512> r;
      r["ok"] = true;
      if (!strcmp(cmd, "ping"))            r["pong"] = "RHP1";
      else if (!strcmp(cmd, "pose")) {
        float x, y, th; readOdometry(&x, &y, &th);
        JsonObject p = r.createNestedObject("pose");
        p["x"] = x; p["y"] = y; p["theta_deg"] = th;
      }
      else if (!strcmp(cmd, "vel")) {
        float l = doc["l"] | 0.0f, a = doc["a"] | 0.0f;
        cmd_v = constrain(l, -MAX_V, MAX_V);
        cmd_w_deg = constrain(a, -MAX_W_DEG, MAX_W_DEG);
      }
      else if (!strcmp(cmd, "stop"))       { cmd_v = 0; cmd_w_deg = 0; }
      else if (!strcmp(cmd, "grab")) {
        bool got = true;                    // replace with real gripper sensing
        gripper(true, doc["name"] | "obj");
        r["grabbed"] = got;
      }
      else if (!strcmp(cmd, "release"))    { gripper(false, ""); }
      else if (!strcmp(cmd, "carrying"))   { r["carrying"] = nullptr; }
      else if (!strcmp(cmd, "objects"))    { r["objects"] = JsonArray(); }
      else { r["ok"] = false; r["error"] = "unknown cmd"; }
      send(r);
    }
  }

  applyRamped(cmd_v, cmd_w_deg);
  delay(10);  // ~100 Hz control loop
}
