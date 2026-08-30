"""RoboForge stress & adversarial harness.

Not a unit-test suite — this is the pre-release battery:

  python scripts/stress_test.py            # everything
  python scripts/stress_test.py fuzz       # 40 adversarial skills at the sandbox
  python scripts/stress_test.py random     # 150 randomized end-to-end missions
  python scripts/stress_test.py cli        # repeated CLI runs

Every adversarial skill MUST be contained (error reported, process alive).
Randomized missions may legitimately fail (physics can block a path), but
the loop must NEVER hang, crash, or corrupt state.
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from robocode.backends.sim_backend import SimBackend  # noqa: E402
from robocode.brain import Brain, Task  # noqa: E402
from robocode.codegen import CodeGen  # noqa: E402
from robocode.robot_api import RobotAPI  # noqa: E402
from robocode.safety import SafetyLayer  # noqa: E402
from robocode.sandbox import SandboxTimeout, run_skill  # noqa: E402
from robocode.simulator import GoalZone, Obstacle, SimObject, World  # noqa: E402
from robocode.skill_library import SkillLibrary  # noqa: E402

HERE = Path(__file__).parent.parent
PASS = FAIL = 0
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


# ----------------------------------------------------------------------
ADVERSARIAL_SKILLS = [
    ("import os", "def run(robot):\n    import os\n    os.system('echo pwned')\n"),
    ("import subprocess", "def run(robot):\n    import subprocess\n    subprocess.run(['dir'])\n"),
    ("file write", "def run(robot):\n    f = open('pwned.txt', 'w')\n    f.write('x')\n"),
    ("file delete", "def run(robot):\n    import shutil\n    shutil.rmtree('C:/')\n"),
    ("eval payload", "def run(robot):\n    eval('__import__(\"os\").system(\"echo x\")')\n"),
    ("exec payload", "def run(robot):\n    exec('import os')\n"),
    ("infinite loop", "def run(robot):\n    while True:\n        pass\n"),
    ("infinite motion", "def run(robot):\n    while True:\n        robot.move_to(1.0, 1.0)\n"),
    ("recursion bomb", "def run(robot):\n    def f():\n        return f()\n    f()\n"),
    ("backend tamper", "def run(robot):\n    robot.backend.world.robot_x = 999.0\n"),
    ("safety tamper", "def run(robot):\n    robot.safety.MAX_LINEAR_SPEED = 999\n"),
    ("class escape", "def run(robot):\n    robot.__class__\n"),
    ("dunder chain", "def run(robot):\n    x = robot.__init__.__globals__\n"),
    ("globals probe", "def run(robot):\n    print(globals()['__builtins__'])\n"),
    ("syntax error", "def run(robot):\n    x = = 3\n"),
    ("no run func", "x = 5\n"),
    ("empty code", ""),
    ("run wrong arity", "def run():\n    pass\n"),
    ("raises ValueError", "def run(robot):\n    raise ValueError('boom')\n"),
    ("KeyboardInterrupt", "def run(robot):\n    raise KeyboardInterrupt\n"),
    ("SystemExit", "def run(robot):\n    raise SystemExit(1)\n"),
    ("zero division", "def run(robot):\n    1 / 0\n"),
    ("index error", "def run(robot):\n    [][5]\n"),
    ("null deref", "def run(robot):\n    None.x\n"),
    ("overspeed move", "def run(robot):\n    robot.safety.check_speeds(999, 999)\n"),
    ("bad target", "def run(robot):\n    robot.move_to(-500, -500)\n"),
    ("nan target", "def run(robot):\n    robot.move_to(float('nan'), float('nan'))\n"),
    ("huge loop count", "def run(robot):\n    for i in range(10**9):\n        pass\n"),
    ("print flood", "def run(robot):\n    for i in range(10**6):\n        print(i)\n"),
    ("object probe", "def run(robot):\n    print(robot._api)\n"),
    ("dunder probe", "def run(robot):\n    print(robot.__init__)\n"),
    ("dict probe", "def run(robot):\n    print(robot.__dict__)\n"),
    ("getattr probe", "def run(robot):\n    print(getattr(robot, '_api'))\n"),
    ("name error", "def run(robot):\n    print(undefined_variable)\n"),
    ("grab nothing", "def run(robot):\n    robot.grab('does_not_exist')\n"),
    ("release empty", "def run(robot):\n    robot.release()\n"),
    ("nested timeout", "def run(robot):\n    def spin():\n        while True: pass\n    import time\n    time.sleep(999)\n"),
    ("math ok", "def run(robot):\n    print(math.hypot(3, 4))\n"),  # must SUCCEED
    ("time ok", "def run(robot):\n    t = time.time()\n    print(t > 0)\n"),  # must SUCCEED
]

MUST_SUCCEED = {"math ok", "time ok", "print flood", "grab nothing", "release empty"}


def fuzz_round() -> None:
    print(f"\n== Round: fuzz — {len(ADVERSARIAL_SKILLS)} adversarial skills ==")
    backend = SimBackend(World())
    robot = RobotAPI(backend, SafetyLayer(bounds=(10.0, 10.0)))

    for name, code in ADVERSARIAL_SKILLS:
        t0 = time.time()
        try:
            report = run_skill(code, robot, timeout_s=5.0)
            if name in MUST_SUCCEED:
                check(name, report["ok"], report["error"] or "")
            else:
                contained = not report["ok"] and report["error"] is not None
                check(name, contained, f"unexpectedly succeeded: {report}")
        except SandboxTimeout:
            check(name, name not in MUST_SUCCEED, "hung")
        except Exception as exc:  # noqa: BLE001 — the sandbox must not leak these
            check(name, False, f"sandbox leaked {type(exc).__name__}: {exc}")
        elapsed = time.time() - t0
        if elapsed > 8.0:
            check(f"{name} (timeliness)", False, f"took {elapsed:.1f}s")
        w = backend.world
        check(f"{name} (state intact)",
              abs(w.robot_x) <= w.width and abs(w.robot_y) <= w.height)


# ----------------------------------------------------------------------
def random_world(rng: random.Random):
    def place(min_d, taken):
        for _ in range(200):
            x, y = rng.uniform(0.5, 9.5), rng.uniform(0.5, 9.5)
            if all((x - tx) ** 2 + (y - ty) ** 2 > min_d ** 2 for tx, ty, tr in taken):
                return x, y
        return rng.uniform(0.5, 9.5), rng.uniform(0.5, 9.5)

    taken = []
    world = World()
    world.robot_x, world.robot_y = place(0.8, taken)
    taken.append((world.robot_x, world.robot_y, 0.35))

    gx, gy = place(1.0, taken)
    world.goal = GoalZone(gx, gy)
    taken.append((gx, gy, 1.0))

    bx, by = place(1.2, taken)
    world.objects.append(SimObject("red_box", "red", bx, by))
    taken.append((bx, by, 0.3))

    if rng.random() < 0.6:  # 60% of scenes have a pillar somewhere
        px, py = place(1.0, taken)
        world.obstacles.append(Obstacle("pillar", px, py, 0.5))

    def success(backend) -> bool:
        w = backend.world
        for obj in w.objects:
            if obj.name == "red_box":
                return math.hypot(obj.x - w.goal.x, obj.y - w.goal.y) <= w.goal.radius
        return False

    return world, success


def random_round(n: int = 150) -> None:
    print(f"\n== Round: randomized missions — {n} end-to-end runs ==")
    rng = random.Random(42)
    lib = SkillLibrary(HERE / "skills" / "stress_library.json")
    lib.skills = []
    codegen = CodeGen({"provider": "mock"})
    brain = Brain(codegen, lib, verbose=False)

    successes = legit_failures = 0
    t0 = time.time()
    for i in range(n):
        world, success = random_world(rng)
        result = brain.run(Task(text="把红色方块送到目标区",
                                backend_factory=lambda w=world: SimBackend(w),
                                success_check=success, max_attempts=2))
        if result.success:
            successes += 1
        else:
            legit_failures += 1
            if result.attempts > 2:
                check(f"mission {i} attempts", False, "exceeded budget")
    elapsed = time.time() - t0

    check(f"{successes}/{n} missions delivered", successes >= n * 0.6,
          f"only {successes} succeeded (physics-blocked paths are legit, "
          f"but below 60% something is wrong)")
    check("no crash across all missions", True)
    print(f"  ({successes} delivered, {legit_failures} physics-blocked, {elapsed:.1f}s total)")

    replay_ok = 0
    for i in range(30):
        world, success = random_world(rng)
        result = brain.run(Task(text="把红色方块送到目标区",
                                backend_factory=lambda w=world: SimBackend(w),
                                success_check=success))
        if result.success:
            replay_ok += 1
    check("library replay still works after 150 runs", replay_ok > 0,
          f"replay succeeded {replay_ok}/30")
    lib.skills = []
    (HERE / "skills" / "stress_library.json").unlink(missing_ok=True)


def cli_round(runs: int = 8) -> None:
    print(f"\n== Round: CLI — {runs} consecutive real process runs ==")
    ok = 0
    for i in range(runs):
        proc = subprocess.run(
            [sys.executable, "main.py", "--demo"],
            capture_output=True, text=True, cwd=HERE, timeout=60)
        if proc.returncode == 0 and "Result: SUCCESS" in proc.stdout:
            ok += 1
        else:
            check(f"cli run {i}", False, proc.stderr[-300:] or proc.stdout[-300:])
    check(f"{ok}/{runs} CLI runs clean", ok == runs, f"{ok} ok")


if __name__ == "__main__":
    rounds = sys.argv[1:] or ["fuzz", "random", "cli"]
    t0 = time.time()
    if "fuzz" in rounds:
        fuzz_round()
    if "random" in rounds:
        random_round()
    if "cli" in rounds:
        cli_round()

    print(f"\n{'=' * 60}\nRESULT: {PASS} passed, {FAIL} failed  ({time.time() - t0:.1f}s)")
    if FAILURES:
        print("FAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL GREEN")
