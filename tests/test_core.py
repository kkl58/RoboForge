"""Core tests: safety, sandbox restrictions, skill library, end-to-end demo.

Run with:  python -m unittest discover tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from robocode.backends.sim_backend import SimBackend  # noqa: E402
from robocode.brain import Brain, Task  # noqa: E402
from robocode.codegen import CodeGen  # noqa: E402
from robocode.robot_api import RobotAPI  # noqa: E402
from robocode.safety import SafetyLayer, SafetyViolation  # noqa: E402
from robocode.sandbox import extract_code, run_skill  # noqa: E402
from robocode.simulator import SimObject, World  # noqa: E402
from robocode.skill_library import SkillLibrary  # noqa: E402

from main import build_demo_world, demo_success  # noqa: E402


def make_robot():
    backend = SimBackend(World())
    return RobotAPI(backend, SafetyLayer(bounds=(10.0, 10.0))), backend


class TestSafety(unittest.TestCase):
    def test_rejects_overspeed(self):
        robot, _ = make_robot()
        with self.assertRaises(SafetyViolation):
            robot.safety.check_speeds(99.0, 0.0)

    def test_rejects_out_of_world_target(self):
        robot, _ = make_robot()
        with self.assertRaises(SafetyViolation):
            robot.move_to(99.0, 99.0)

    def test_rejects_negative_target(self):
        robot, _ = make_robot()
        with self.assertRaises(SafetyViolation):
            robot.move_to(-3.0, 1.0)

    def test_rejects_nan_target(self):
        robot, _ = make_robot()
        with self.assertRaises(SafetyViolation):
            robot.move_to(float("nan"), 1.0)

    def test_no_bounds_allows_free_roaming_but_rejects_garbage(self):
        safety = SafetyLayer()  # real robot: no fixed work area
        safety.check_target(1000.0, 1000.0)  # fine
        with self.assertRaises(SafetyViolation):
            safety.check_target(float("inf"), 0.0)


class TestSandbox(unittest.TestCase):
    def test_no_imports_allowed(self):
        robot, _ = make_robot()
        report = run_skill(
            "def run(robot):\n    import os\n    robot.log(os.getcwd())\n", robot)
        self.assertFalse(report["ok"])
        self.assertIn("ImportError", report["error"] or "ImportError")

    def test_no_file_io(self):
        robot, _ = make_robot()
        report = run_skill('def run(robot):\n    open("x.txt", "w")\n', robot)
        self.assertFalse(report["ok"])

    def test_timeout_kills_runaway_loop(self):
        robot, _ = make_robot()
        with self.assertRaises(Exception):
            run_skill("def run(robot):\n    while True:\n        pass\n",
                      robot, timeout_s=2.0)

    def test_extract_code_from_fenced_output(self):
        raw = "Here you go:\n```python\ndef run(robot):\n    pass\n```\nDone."
        self.assertIn("def run", extract_code(raw))

    def test_sandbox_escape_via_sim_is_blocked(self):
        robot, backend = make_robot()
        report = run_skill(
            'def run(robot):\n    robot.backend.world.robot_x = 999.0\n', robot)
        self.assertFalse(report["ok"])
        self.assertIn("AttributeError", report["error"])
        self.assertNotEqual(backend.world.robot_x, 999.0)

    def test_underscore_and_dunder_are_blocked(self):
        robot, _ = make_robot()
        for probe in ("robot._api", "robot.__class__", "robot.__dict__",
                      "robot.__init__.__globals__", 'getattr(robot, "_api")'):
            report = run_skill(f"def run(robot):\n    print({probe})\n", robot)
            self.assertFalse(report["ok"], probe)

    def test_proxy_forwards_real_api_calls(self):
        robot, _ = make_robot()
        report = run_skill(
            'def run(robot):\n'
            '    p = robot.get_position()\n'
            '    print(p["x"], p["y"])\n', robot)
        self.assertTrue(report["ok"], report["error"])
        self.assertEqual(report["output"], ["1.0 1.0"])

    def test_print_flood_is_capped_not_fatal(self):
        robot, _ = make_robot()
        report = run_skill(
            "def run(robot):\n    for i in range(10**6):\n        print(i)\n",
            robot, timeout_s=30.0)
        self.assertTrue(report["ok"], report["error"])


class TestSkillLibrary(unittest.TestCase):
    def test_save_find_replay(self):
        lib = SkillLibrary(Path(__file__).parent / "tmp_library.json")
        lib.skills = []
        lib.save("deliver the red box to the goal zone", "def run(robot):\n    pass\n",
                 verified=True, source="mock")
        hit = lib.find("move the blue box next to the goal zone")
        self.assertIsNotNone(hit)
        lib.skills = []
        (Path(__file__).parent / "tmp_library.json").unlink(missing_ok=True)


class TestEndToEnd(unittest.TestCase):
    class _FlakyGen:
        """Simulates an unreliable model: bad first draft, fixed second draft."""
        provider = "mock"

        def __init__(self):
            self.calls = 0

        def generate(self, task, scene, feedback=""):
            self.calls += 1
            if self.calls == 1:
                return ("```python\n"
                        "def run(robot):\n"
                        "    robot.move_to(99.0, 99.0)\n"  # out of work area
                        "```\n")
            return ("```python\n"
                    "def run(robot):\n"
                    "    robot.move_to(3.0, 3.0)\n"
                    "```\n")

    def test_retry_with_feedback_recovers_from_bad_code(self):
        lib = SkillLibrary(Path(__file__).parent / "tmp_flaky.json")
        lib.skills = []
        brain = Brain(self._FlakyGen(), lib, verbose=False)
        result = brain.run(Task(
            text="walk to 3 3",
            backend_factory=lambda: SimBackend(World()),
            success_check=lambda b: abs(b.world.robot_x - 3.0) < 0.3
                                    and abs(b.world.robot_y - 3.0) < 0.3))
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        lib.skills = []
        (Path(__file__).parent / "tmp_flaky.json").unlink(missing_ok=True)

    def test_real_openai_http_path(self):
        """Exercise the actual network client against a local OpenAI-compatible server."""
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received["url"] = self.path
                received["auth"] = self.headers["Authorization"]
                received["model"] = _json.loads(body)["model"]
                payload = _json.dumps({"choices": [{"message": {"content":
                    "```python\ndef run(robot):\n    robot.move_to(2.0, 2.0)\n```\n"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            codegen = CodeGen({"provider": "openai",
                               "base_url": f"http://127.0.0.1:{server.server_port}",
                               "api_key": "test-key", "model": "glm-5.3-flash"})
            lib = SkillLibrary(Path(__file__).parent / "tmp_http.json")
            lib.skills = []
            brain = Brain(codegen, lib, verbose=False)
            result = brain.run(Task(
                text="walk to 2 2",
                backend_factory=lambda: SimBackend(World()),
                success_check=lambda b: abs(b.world.robot_x - 2.0) < 0.3))
            self.assertTrue(result.success, result.log)
            self.assertEqual(result.source, "openai")
            self.assertEqual(received["url"], "/chat/completions")
            self.assertEqual(received["auth"], "Bearer test-key")
            self.assertEqual(received["model"], "glm-5.3-flash")
            lib.skills = []
            (Path(__file__).parent / "tmp_http.json").unlink(missing_ok=True)
        finally:
            server.shutdown()

    def test_demo_task_succeeds_offline(self):
        codegen = CodeGen({"provider": "mock"})
        lib = SkillLibrary(Path(__file__).parent / "tmp_e2e.json")
        lib.skills = []
        brain = Brain(codegen, lib, verbose=False)
        result = brain.run(Task(
            text="Deliver the red box (red_box) to the goal zone in the top-right",
            backend_factory=lambda: SimBackend(build_demo_world()),
            success_check=demo_success))
        self.assertTrue(result.success, result.log)
        self.assertIsNotNone(result.backend)

        hit = lib.find("Deliver the red box (red_box) to the goal zone in the top-right")
        self.assertIsNotNone(hit)
        lib.skills = []
        (Path(__file__).parent / "tmp_e2e.json").unlink(missing_ok=True)

    def test_success_check_requires_box_in_goal(self):
        backend = SimBackend(build_demo_world())
        self.assertFalse(demo_success(backend))
        backend.world.objects = [SimObject(name="red_box", color="red",
                                           x=backend.world.goal.x,
                                           y=backend.world.goal.y)]
        self.assertTrue(demo_success(backend))


if __name__ == "__main__":
    unittest.main()
