# RoboForge 🤖

**English** | [中文](README.zh-CN.md)

![version](https://img.shields.io/badge/version-v0.1--alpha-blueviolet)
![status](https://img.shields.io/badge/status-alpha·actively%20developed-orange)

**Let an LLM watch the scene and write the robot's code on the fly.**

> 📌 **Status**: this is the **v0.1 starting release** (alpha). The core loop works
> and passes all tests, but there is a long road ahead — real-robot firmware needs
> chassis adaptation, perception needs calibration, the skill library needs semantic
> retrieval, plus voice input and more robot forms (arms, legged). **It will keep
> improving** — stars, issues and PRs are all welcome.
>
> ✍️ **Author**: a first-year undergrad (see the account profile). The project
> started from one question: *"Can a robot solve new tasks by writing its own
> code on the spot, instead of waiting for a human to program it?"* If you are a
> student too, this project wants to tell you: you can build right now the thing
> you thought only big companies could build.

RoboForge is a lightweight, open-source implementation of the
"code-as-policies" idea: instead of hard-coded robot behaviors, an LLM
watches the scene and **writes a Python skill on the fly**, which is
sandboxed, safety-checked, verified, then executed — and cached into a
skill library so similar tasks are later answered with **zero model
calls**. The same generated skill runs in simulation, on a $20 ESP32
over WiFi, on an STM32 over serial, or inside a ROS 2 stack.

> You write zero robot code. You just say the task.

```
=== Task: deliver the red box to the goal zone (top-right) ===
[brain] attempt 1: asking the model to write a skill...
  [skill] found red_box at 5.0 3.0
  [skill] carrying red_box
  [skill] delivered red_box to [8.0, 8.0]
[brain] success check PASSED
[brain] verified and saved as skill_001
Result: SUCCESS (attempts=1, source=mock, skill=skill_001)

# second run of the same task:
Result: SUCCESS (attempts=1, source=library, skill=skill_001)   ← zero model calls
```

## How it works

```
        ┌─────────────────────────────────────────────────────┐
        │  You: "put the red box into the goal zone"           │
        └───────────────────────┬─────────────────────────────┘
                                ▼
            ① skill library lookup (verified skill? replay it)
                                ▼ miss
            ② LLM writes a skill at runtime   def run(robot): ...
                                ▼
            ③ sandbox — whitelist proxy only, no imports/IO,
               watchdog thread kills runaway loops
                                ▼
            ④ safety layer — hard speed/target/time limits,
               unreachable by the model, ever
                                ▼
            ⑤ execution — through the HAL to any body
                                ▼
            ⑥ skill library — verified skills cached & reused
```

Design principle: **the model only "writes", it never "guarantees"**.
Generated code is probabilistic, so every layer has deterministic
guardrails: the sandbox limits what it can touch, the safety layer
limits where it can go, the HAL keeps behavior identical in sim and on
real hardware, and the skill library means trusted code never needs a
second generation.

## Connect a real robot

Every body implements the same [HAL interface](robocode/backends/__init__.py).
Pick it with `--backend` in chat mode — generated skills do not change
a single line:

```bash
python main.py --chat --backend sim                                  # simulation
python main.py --chat --backend serial --port COM3                   # USB/serial
python main.py --chat --backend serial --port /dev/ttyUSB0           # Linux serial
python main.py --chat --backend http   --base-url http://192.168.4.1 # WiFi robot
python main.py --chat --backend ros2                                 # ROS 2 robot
```

| Backend | For | Dependencies |
|---|---|---|
| `sim` | built-in 2D sim, zero-cost experiments | none (stdlib only) |
| `serial` | Arduino / ESP32 / STM32 serial chassis | `pip install pyserial` for real ports |
| `http` | ESP32-style WiFi robots (REST control) | none |
| `ros2` | TurtleBot-style industry stacks | ROS 2 on the robot |

**The robot "body" side**: [firmware/](firmware/) ships reference firmware
and a protocol spec — [PROTOCOL.md](firmware/PROTOCOL.md) (JSON-lines over
serial + HTTP routes) —

- `firmware/arduino_roboforge_rhp1.ino` — Arduino/ESP32 serial firmware (100 Hz control loop, velocity ramping, 500 ms watchdog, e-stop)
- `firmware/esp32_http_server.ino` — ESP32 WiFi firmware (REST routes)
- `firmware/stm32_keil_main.c` — STM32/Keil MDK template (CubeMX integration notes included)

The firmware side must own its protection: watchdog (brain silent for
500 ms → stop), velocity ramping, hardware e-stop, encoder odometry.
**The PC-side safety layer is the second line of defense — it can never
replace firmware guardrails.**

**The robot "eyes"** (real-world perception, `robocode/vision.py`): three
sources, one output format

- `StaticMapVision` — operator-calibrated object table (get running first)
- `VLMVision` — camera frame + multimodal LLM (GLM / Qwen-VL / any
  OpenAI-compatible endpoint) returns object coordinates in real time
  (needs `opencv-python`)
- in simulation, perfect perception is automatic

## Quick start

Zero dependencies (pure Python stdlib, Python ≥ 3.10):

```bash
# offline demo: built-in mock model, no API key needed
python main.py --demo --map

# tests (fake-firmware serial conformance + real HTTP server integration)
python -m unittest discover tests -v

# stress: 40 adversarial skills vs the sandbox + 150 randomized missions + CLI runs
python scripts/stress_test.py
```

Plug in a real LLM (GLM / DeepSeek / any OpenAI-compatible endpoint):

```bash
cp config.example.json config.json   # put your api_key in
python main.py --chat                # chat mode: talk → think → write code → act
```

`config.json`:

```json
{
  "provider": "openai",
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_key": "YOUR_API_KEY",
  "model": "glm-5.3-flash",
  "backend": {"type": "sim"},
  "work_area": [10.0, 10.0]
}
```

## Project layout

```
robocode/
  simulator.py     2D physics sim: differential drive, obstacles, pushable objects
  backends/        HAL: sim / serial / http / ros2 bodies
  robot_api.py     RobotAPI — the ONLY surface generated code can touch
  safety.py        hard safety layer: speed/target/time limits, plain constants
  sandbox.py       sandbox: whitelist proxy, no imports/underscores, watchdog
  vision.py        perception: sim / static calibration / camera + VLM
  codegen.py       LLM client (OpenAI-compatible + built-in mock)
  skill_library.py skill library: verified skills cached & retrieved
  brain.py         orchestration: lookup → generate → sandbox → verify → store
  chat.py          chat interface
firmware/          RHP1 protocol spec + Arduino/ESP32/STM32 reference firmware
tests/             unit tests + backend conformance (fake firmware / real HTTP)
scripts/           stress & adversarial battery
```

## Known limits (honest disclosure)

- Real-robot firmware is reference code: pin mapping, encoders and grippers
  need chassis adaptation; the protocol itself is covered by conformance
  tests (the fake firmware in tests speaks exactly PROTOCOL.md).
- VLM perception needs calibration (pixels → meters); accuracy depends on
  camera and model.
- Skill retrieval is lexical (words for English, characters for Chinese);
  embedding-based retrieval is the obvious next step.
- Passing in simulation ≠ passing on hardware. Keep the firmware watchdog
  and e-stop when deploying for real.

## Similar projects

- [google-research/code-as-policies](https://github.com/google-research/code-as-policies) — the origin of this idea (ICRA 2023)
- VoxPoser, GenSwarm and follow-ups — LLM-generated robot control programs

## License

MIT
