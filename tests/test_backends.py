"""Backend conformance suite: every HardwareBackend must behave identically.

- serial: tested against a FAKE FIRMWARE DEVICE implementing RHP1 over an
  in-memory transport (the exact bytes a real Arduino/ESP32/STM32 would speak)
- http:   tested against a real local HTTP server (the same routes as the
  ESP32 reference firmware)
- ros2:   conformance runs only if rclpy is installed (skipped otherwise)
- chat:   end-to-end REPL session on the sim backend
"""

from __future__ import annotations

import json
import math
import sys
import threading
import unittest
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from robocode.backends import make_backend  # noqa: E402
from robocode.backends.http_backend import HttpBackend  # noqa: E402
from robocode.backends.serial_backend import SerialBackend  # noqa: E402
from robocode.backends.sim_backend import SimBackend  # noqa: E402
from robocode.brain import Brain, Task  # noqa: E402
from robocode.chat import chat_session  # noqa: E402
from robocode.codegen import CodeGen  # noqa: E402
from robocode.skill_library import SkillLibrary  # noqa: E402

from main import build_demo_world, demo_success  # noqa: E402

HERE = Path(__file__).parent


# ======================================================================
class FakeFirmwareDevice:
    """A Python implementation of RHP1 serial firmware — the same JSON
    lines a real Arduino/ESP32/STM32 body would exchange. World model:
    differential drive, dead reckoning, one grabbable box."""

    def __init__(self):
        self.x, self.y, self.th = 1.0, 1.0, 0.0
        self.v, self.w = 0.0, 0.0
        self.box = {"name": "red_box", "color": "red", "x": 3.0, "y": 3.0}
        self.carrying = None
        self.inbox: deque[bytes] = deque()
        self.outbox: deque[bytes] = deque()
        self.alive = True

    # --- transport side (what SerialBackend sees) ---
    def write(self, data: bytes) -> None:
        self.inbox.extend(data.split(b"\n"))

    def read(self, n: int) -> bytes:
        if self.outbox:
            return self.outbox.popleft()
        return b""

    def tick(self, dt: float = 0.05) -> None:
        """Physics on the body, 20 Hz — exactly like real firmware."""
        while self.inbox:
            line = self.inbox.popleft().strip()
            if line:
                self._handle(line.decode())
        if self.carrying:
            self.box["x"], self.box["y"] = self.x, self.y
        self.x += self.v * math.cos(math.radians(self.th)) * dt
        self.y += self.v * math.sin(math.radians(self.th)) * dt
        self.th = (self.th + self.w * dt) % 360.0

    def _reply(self, obj: dict) -> None:
        self.outbox.append((json.dumps(obj) + "\n").encode())

    def _handle(self, line: str) -> None:
        msg = json.loads(line)
        cmd = msg.get("cmd")
        if cmd == "ping":
            self._reply({"ok": True, "pong": "RHP1"})
        elif cmd == "pose":
            self._reply({"ok": True, "pose": {"x": round(self.x, 3),
                                              "y": round(self.y, 3),
                                              "theta_deg": round(self.th, 1)}})
        elif cmd == "vel":
            self.v = max(-1.5, min(1.5, float(msg.get("l", 0))))
            self.w = max(-60.0, min(60.0, float(msg.get("a", 0))))
            self._reply({"ok": True})
        elif cmd == "stop":
            self.v = self.w = 0.0
            self._reply({"ok": True})
        elif cmd == "grab":
            d = math.hypot(self.box["x"] - self.x, self.box["y"] - self.y)
            if not self.carrying and d <= 0.9:
                self.carrying = self.box["name"]
                self._reply({"ok": True, "grabbed": True})
            else:
                self._reply({"ok": True, "grabbed": False})
        elif cmd == "release":
            self.carrying = None
            self._reply({"ok": True})
        elif cmd == "carrying":
            self._reply({"ok": True, "carrying": self.carrying})
        elif cmd == "objects":
            self._reply({"ok": True, "objects": [dict(self.box)]})
        else:
            self._reply({"ok": False, "error": "unknown cmd"})


class FakeSerialTransport:
    """Bidirectional pipe between SerialBackend and FakeFirmwareDevice,
    with a background thread ticking the device's physics."""

    def __init__(self):
        self.device = FakeFirmwareDevice()
        self._lock = threading.Lock()

    # SerialBackend side
    def write(self, data: bytes) -> None:
        with self._lock:
            self.device.write(data)

    def read(self, n: int) -> bytes:
        with self._lock:
            return self.device.read(n)

    def start(self):
        def loop():
            import time
            while self.device.alive:
                with self._lock:
                    self.device.tick()
                time.sleep(0.005)
        threading.Thread(target=loop, daemon=True).start()


def _conformance_suite(backend, work_area=None):
    """The behavioral contract every backend must satisfy."""
    from robocode.robot_api import RobotAPI
    from robocode.safety import SafetyLayer

    robot = RobotAPI(backend, SafetyLayer(bounds=work_area))
    pose = robot.get_position()
    assert {"x", "y", "theta_deg"} <= set(pose), pose

    # turn and drive
    assert robot.turn_to(90.0)
    assert abs(robot.get_position()["theta_deg"] - 90.0) < 5.0
    assert robot.move_to(2.0, 2.0, timeout_s=25.0)
    pose = robot.get_position()
    assert math.hypot(pose["x"] - 2.0, pose["y"] - 2.0) < 0.3, pose

    objects = robot.sense_objects()
    assert isinstance(objects, list)

    # grab near an object that exists in this backend's world
    if objects:
        target = objects[0]
        robot.move_to(target["x"], target["y"], timeout_s=25.0)
        got = robot.grab(target["name"])
        assert isinstance(got, bool)
        robot.release()

    robot.stop()
    return True


class TestSerialBackendConformance(unittest.TestCase):
    def test_full_conformance_over_rhp1_protocol(self):
        transport = FakeSerialTransport()
        transport.start()
        backend = SerialBackend(port=transport)   # handshake must succeed
        self.assertEqual(backend._handshake.get("pong"), "RHP1")
        self.assertTrue(_conformance_suite(backend))

    def test_pingless_device_is_rejected(self):
        class MuteDevice(FakeSerialTransport):
            pass

        class Silent:
            def write(self, data): pass
            def read(self, n): return b""

        with self.assertRaises(ConnectionError):
            SerialBackend(port=Silent())

    def test_garbage_lines_do_not_crash(self):
        transport = FakeSerialTransport()
        transport.start()
        backend = SerialBackend(port=transport)      # clean handshake first
        device = transport.device
        device.outbox.append(b"\xff\xfe garbage\n")  # then pollute the line
        device.outbox.append(b"{}\n")
        device.outbox.append(b"not json at all\n")
        pose = backend.get_pose()                    # retries skip the junk
        self.assertIn("x", pose)


class TestHttpBackendConformance(unittest.TestCase):
    def _make_server(self):
        state = {"x": 1.0, "y": 1.0, "th": 0.0, "v": 0.0, "w": 0.0,
                 "carrying": None}
        box = {"name": "red_box", "color": "red", "x": 3.0, "y": 3.0}

        class Handler(BaseHTTPRequestHandler):
            def _send(self, obj):
                payload = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _step(self):
                dt = 0.02
                state["x"] += state["v"] * math.cos(math.radians(state["th"])) * dt
                state["y"] += state["v"] * math.sin(math.radians(state["th"])) * dt
                state["th"] = (state["th"] + state["w"] * dt) % 360.0
                if state["carrying"]:
                    box["x"], box["y"] = state["x"], state["y"]

            def do_GET(self):
                self._step()
                if self.path == "/ping":
                    self._send({"ok": True, "pong": "RHP1"})
                elif self.path == "/pose":
                    self._send({"ok": True, "pose": {
                        "x": round(state["x"], 3), "y": round(state["y"], 3),
                        "theta_deg": round(state["th"], 1)}})
                elif self.path == "/carrying":
                    self._send({"ok": True, "carrying": state["carrying"]})
                elif self.path == "/objects":
                    self._send({"ok": True, "objects": [dict(box)]})
                else:
                    self._send({"ok": False, "error": "no route"})

            def do_POST(self):
                self._step()
                body = json.loads(self.rfile.read(
                    int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path == "/vel":
                    state["v"] = max(-1.5, min(1.5, float(body.get("l", 0))))
                    state["w"] = max(-60.0, min(60.0, float(body.get("a", 0))))
                    self._send({"ok": True})
                elif self.path == "/stop":
                    state["v"] = state["w"] = 0.0
                    self._send({"ok": True})
                elif self.path == "/grab":
                    d = math.hypot(box["x"] - state["x"], box["y"] - state["y"])
                    if not state["carrying"] and d <= 0.9:
                        state["carrying"] = box["name"]
                        self._send({"ok": True, "grabbed": True})
                    else:
                        self._send({"ok": True, "grabbed": False})
                elif self.path == "/release":
                    state["carrying"] = None
                    self._send({"ok": True})
                else:
                    self._send({"ok": False, "error": "no route"})

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def test_full_conformance_over_http(self):
        server = self._make_server()
        try:
            backend = HttpBackend(f"http://127.0.0.1:{server.server_port}")
            self.assertTrue(_conformance_suite(backend))
        finally:
            server.shutdown()


class TestSimBackendConformance(unittest.TestCase):
    def test_full_conformance_in_simulation(self):
        self.assertTrue(_conformance_suite(
            SimBackend(build_demo_world()), work_area=(10.0, 10.0)))


class TestRos2Backend(unittest.TestCase):
    def test_ros2_conformance_if_available(self):
        try:
            import rclpy  # noqa: F401
        except ImportError:
            self.skipTest("rclpy not installed — ROS 2 backend code still ships")
        from robocode.backends.ros2_backend import Ros2Backend
        backend = Ros2Backend()
        self.assertTrue(_conformance_suite(backend))


class TestRegistry(unittest.TestCase):
    def test_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            make_backend({"type": "teleporter"})

    def test_sim_backend_from_config(self):
        self.assertIsInstance(make_backend({"type": "sim"}), SimBackend)


class TestChatSession(unittest.TestCase):
    def test_chat_session_on_sim(self):
        import os
        os.chdir(HERE.parent)  # skill library paths resolve from repo root
        codegen_cfg = {"provider": "mock"}
        try:
            transcript = chat_session(
                codegen_cfg, SimBackend(build_demo_world()),
                utterances=["Deliver the red box (red_box) to the goal zone in the top-right", "quit"],
                verbose=False)
        finally:
            os.chdir(HERE.parent)
        self.assertEqual(len(transcript), 1)
        self.assertEqual(transcript[0]["result"], "done")
        lib = SkillLibrary(HERE.parent / "skills" / "chat_library.json")
        lib.skills = []
        (HERE.parent / "skills" / "chat_library.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
