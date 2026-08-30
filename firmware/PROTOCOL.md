# RoboForge Hardware Protocol v1 (RHP1)

**English** | [中文](#中文版)

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


---

# 中文版

**一份协议，多种载体。** 大脑（PC）与身体（机器人）之间通过**串口（USB/UART/蓝牙串口）**
或 **HTTP（WiFi）** 通信，消息完全一致。本目录附带参考固件；一致性由
tests/test_backends.py 中的假固件设备保证（它说的就是这份协议的话）。

## 单位与坐标系

- 距离单位**米**，角度**度**，速度 **m/s** 与 **deg/s**
- 世界坐标系：x 向右，y 向前(上)，theta 0° = +x 方向，逆时针为正
- 机器人为差速底盘；固件端把 `v, w` 换算成左右轮速：
  `v_l = v - w*轮距/2`，`v_r = v + w*轮距/2`（固件内部角度用弧度）

## 串口传输（JSON 行，115200 8N1）

每条消息为**一行**以 `
` 结尾的 JSON。每条命令必须恰好回复一行，
固件须在 50 ms 内应答。

### PC → 机器人

```json
{"cmd": "ping"}
{"cmd": "pose"}
{"cmd": "vel", "l": 0.5, "a": 10.0}       // 锁存速度；a 单位 deg/s
{"cmd": "stop"}
{"cmd": "grab", "name": "red_box"}
{"cmd": "release"}
{"cmd": "carrying"}
{"cmd": "objects"}                          // 身体端有感知时
```

### 机器人 → PC

```json
{"ok": true, "pong": "RHP1"}                       // ping 应答（magic = 身份标识）
{"ok": true, "pose": {"x": 1.0, "y": 2.0, "theta_deg": 90.0}}
{"ok": true}                                        // vel / stop / release 应答
{"ok": true, "grabbed": false}                      // grab 应答
{"ok": true, "carrying": null}
{"ok": true, "objects": [{"name": "red_box", "color": "red", "x": 3.0, "y": 2.0}]}
{"ok": false, "error": "e-stop latched"}            // 任何失败
```

规则：
- `ok:false` 时固件端必须同时把速度锁存为零。
- 固件应自带急停、限位开关与电流保护；PC 侧安全层是第二道防线，**永远不能替代固件护栏**。

## HTTP 传输（WiFi，如 ESP32）

| 方法 | 路径      | 请求体                        | 回复 |
|------|-----------|-------------------------------|------|
| GET  | /ping     | –                             | `{"ok":true,"pong":"RHP1"}` |
| GET  | /pose     | –                             | 同上 |
| POST | /vel      | `{"l":0.5,"a":10.0}`          | `{"ok":true}` |
| POST | /stop     | –                             | `{"ok":true}` |
| POST | /grab     | `{"name":"red_box"}`          | `{"ok":true,"grabbed":false}` |
| POST | /release  | –                             | `{"ok":true}` |
| GET  | /carrying | –                             | `{"ok":true,"carrying":null}` |
| GET  | /objects  | –                             | 同上 |

## 身体端必须实现的功能（固件清单）

- 50–200 Hz 内部控制环（PC 只下发设定值）
- 速度斜坡限制（禁止瞬间满油门）
- 硬件急停输入 + 看门狗：500 ms 无消息 → 停止
- 里程计：编码器 → x, y, theta
- 可选：夹爪舵机、碰撞传感器、电流检测
