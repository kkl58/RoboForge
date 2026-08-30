# RoboForge Hardware Protocol v1 (RHP1)

One protocol, any transport. The PC brain talks to the robot body over
**serial (USB/UART/蓝牙串口)** or **HTTP (WiFi)** using the same messages.
Reference firmware lives in this folder; conformance is tested against a
fake device implementing this exact spec (tests/test_backends.py).

## Units & frames

- distances in **meters**, angles in **degrees**, speeds in **m/s** and **deg/s**
- world frame: x right, y forward(up), theta 0° = +x, counter-clockwise positive
- robot is a differential-drive base; firmware may translate `v, w` to
  left/right wheel speeds: `v_l = v - w_wheel_track/2`, `v_r = v + w_wheel_track/2`
  (angles in rad on the firmware side)

## Serial transport (JSON lines, 115200 8N1)

Each message is ONE line of JSON ending in `\n`. Every command gets exactly
one reply line. Firmware MUST reply within 50 ms.

### PC -> robot

```json
{"cmd": "ping"}
{"cmd": "pose"}
{"cmd": "vel", "l": 0.5, "a": 10.0}       // latch velocities; a in deg/s
{"cmd": "stop"}
{"cmd": "grab", "name": "red_box"}
{"cmd": "release"}
{"cmd": "carrying"}
{"cmd": "objects"}                          // if the body has perception
```

### Robot -> PC

```json
{"ok": true, "pong": "RHP1"}                       // ping reply (magic = identity)
{"ok": true, "pose": {"x": 1.0, "y": 2.0, "theta_deg": 90.0}}
{"ok": true}                                        // vel / stop / release ack
{"ok": true, "grabbed": false}                      // grab reply
{"ok": true, "carrying": null}
{"ok": true, "objects": [{"name": "red_box", "color": "red", "x": 3.0, "y": 2.0}]}
{"ok": false, "error": "e-stop latched"}            // any failure
```

Rules:
- `ok:false` MUST also latch zero velocity on the firmware side.
- firmware SHOULD implement its own e-stop, limit switches and current
  caps; the PC safety layer is a second line of defense, never a substitute.

## HTTP transport (WiFi, e.g. ESP32)

| Method | Path      | Body                          | Reply |
|--------|-----------|-------------------------------|-------|
| GET    | /ping     | –                             | `{"ok":true,"pong":"RHP1"}` |
| GET    | /pose     | –                             | as above |
| POST   | /vel      | `{"l":0.5,"a":10.0}`          | `{"ok":true}` |
| POST   | /stop     | –                             | `{"ok":true}` |
| POST   | /grab     | `{"name":"red_box"}`          | `{"ok":true,"grabbed":false}` |
| POST   | /release  | –                             | `{"ok":true}` |
| GET    | /carrying | –                             | `{"ok":true,"carrying":null}` |
| GET    | /objects  | –                             | as above |

## What the body MUST own (firmware checklist)

- 50–200 Hz internal control loop (PC only sends setpoints)
- velocity ramp limiting (no instant full-throttle)
- hard e-stop input + watchdog: no message for 500 ms → stop
- odometry: wheel encoders → x, y, theta
- optional: gripper servo, bumpers, current sensing
