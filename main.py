"""RoboForge demo & CLI.

  python main.py --demo            run the built-in demo offline (mock provider)
  python main.py --task "..."      one-shot task with a real LLM via config.json
  python main.py --chat            interactive: talk, the robot thinks and acts
  python main.py --chat --backend serial --port COM3      real robot (USB/UART)
  python main.py --chat --backend http  --base-url http://192.168.4.1   (WiFi)
  python main.py --chat --backend ros2                    (ROS 2 stack)
  python main.py --map             show the scene before running
"""

from __future__ import annotations

import argparse
from pathlib import Path

from robocode.backends import make_backend
from robocode.backends.sim_backend import SimBackend
from robocode.brain import Brain, Task
from robocode.codegen import CodeGen
from robocode.simulator import GoalZone, Obstacle, SimObject, World
from robocode.skill_library import SkillLibrary

HERE = Path(__file__).parent


def build_demo_world() -> World:
    """A small warehouse: robot starts bottom-left, red box mid-field,
    a pillar in the way, goal zone top-right."""
    world = World()
    world.objects = [SimObject(name="red_box", color="red", x=5.0, y=3.0),
                     SimObject(name="blue_box", color="blue", x=7.0, y=6.0)]
    world.obstacles = [Obstacle(name="pillar", x=4.0, y=6.0, radius=0.5)]
    world.goal = GoalZone(x=8.0, y=8.0, radius=1.0)
    return world


def demo_success(backend: SimBackend) -> bool:
    """Success: the red box ends up inside the goal zone."""
    world = backend.world
    for obj in world.objects:
        if obj.name == "red_box":
            return ((obj.x - world.goal.x) ** 2 + (obj.y - world.goal.y) ** 2) ** 0.5 \
                <= world.goal.radius
    return False


def load_config() -> dict:
    path = HERE / "config.json"
    if path.exists():
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    return {"provider": "mock", "backend": {"type": "sim"}}


def main() -> None:
    parser = argparse.ArgumentParser(description="RoboForge — the robot that writes its own code")
    parser.add_argument("--demo", action="store_true", help="run the built-in offline demo")
    parser.add_argument("--task", type=str, help="natural-language task for a real LLM")
    parser.add_argument("--chat", action="store_true",
                        help="interactive session: talk, the robot thinks and acts")
    parser.add_argument("--backend", choices=["sim", "serial", "http", "ros2"],
                        help="hardware backend (default: sim)")
    parser.add_argument("--port", type=str, help="serial port, e.g. COM3 or /dev/ttyUSB0")
    parser.add_argument("--base-url", type=str, help="WiFi robot base URL for --backend http")
    parser.add_argument("--map", action="store_true", help="print the scene map first")
    args = parser.parse_args()

    config = load_config()

    if args.chat:
        from robocode.chat import chat_session
        backend = make_backend({k: v for k, v in {
            "type": args.backend or config.get("backend", {}).get("type", "sim"),
            "port": args.port, "base_url": args.base_url}.items() if v is not None})
        chat_session(config, backend)
        return

    codegen = CodeGen(config)
    library = SkillLibrary(HERE / "skills" / "library.json")
    brain = Brain(codegen, library)
    task = Task(
        text=args.task or "Deliver the red box (red_box) to the goal zone in the top-right",
        backend_factory=lambda: SimBackend(build_demo_world()),
        success_check=demo_success)

    if args.map:
        print(SimBackend(build_demo_world()).render_map())

    result = brain.run(task)

    print("\n--- final scene ---")
    if result.backend is not None and hasattr(result.backend, "render_map"):
        print(result.backend.render_map())
    print(f"\nResult: {'SUCCESS' if result.success else 'FAILED'} "
          f"(attempts={result.attempts}, source={result.source}, skill={result.skill_id})")

    if result.success:
        print("\nTip: run the same task again — it will be replayed from the "
              "skill library with zero model calls.")


if __name__ == "__main__":
    main()
