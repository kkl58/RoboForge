"""RoboForge chat — talk to the robot, it thinks, writes its own code, acts.

  python main.py --chat                       # simulated robot
  python main.py --chat --backend serial --port COM3
  python main.py --chat --backend http --base-url http://192.168.4.1

Each utterance becomes a task; the brain looks in the skill library,
asks the model for code when needed, executes it behind the safety
layer, and reports what happened. Verified skills accumulate, so the
robot gets faster and more reliable the more you use it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .backends import make_backend
from .brain import Brain, Task
from .codegen import CodeGen
from .safety import SafetyLayer
from .skill_library import SkillLibrary
from .vision import VisionBackendAdapter


def _backend_from_args(config: dict, args) -> object:
    backend_cfg = dict(config.get("backend", {"type": "sim"}))
    if args is not None:
        if getattr(args, "backend", None):
            backend_cfg["type"] = args.backend
        if getattr(args, "port", None):
            backend_cfg["port"] = args.port
        if getattr(args, "base_url", None):
            backend_cfg["base_url"] = args.base_url
    return make_backend(backend_cfg)


def chat_session(config: dict, backend, utterances: list[str] | None = None,
                 verbose: bool = True) -> list[dict]:
    """Run one chat session. `utterances` given -> non-interactive (tests)."""
    codegen = CodeGen(config)
    here = Path(__file__).parent.parent
    library = SkillLibrary(here / "skills" / "chat_library.json")
    brain = Brain(codegen, library, verbose=verbose)
    safety = SafetyLayer(bounds=config.get("work_area"))

    # real perception (if configured) feeds the scene the model sees
    vision_cfg = config.get("vision")
    if vision_cfg and vision_cfg.get("type") == "static_map":
        from .vision import StaticMapVision, VisionBackendAdapter
        backend = VisionBackendAdapter(backend, StaticMapVision(vision_cfg["objects"]))

    transcript: list[dict] = []
    lines = iter(utterances)
    while True:
        if utterances is None:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
        else:
            text = next(lines, None)
            if text is None:
                break
        if not text or text.lower() in {"quit", "exit", "q"}:
            print("robot> bye")
            break

        backend_factory = lambda b=backend: b  # same robot in reality
        result = brain.run(Task(text=text, backend_factory=backend_factory,
                                success_check=lambda b: True, safety=safety,
                                max_attempts=2))
        status = "done" if result.success else "failed"
        print(f"robot> {status}")
        transcript.append({"you": text, "result": status,
                           "skill": result.skill_id, "source": result.source})
    return transcript


def load_config(path: str | Path = None) -> dict:
    p = Path(path) if path else Path(__file__).parent.parent / "config.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"provider": "mock", "backend": {"type": "sim"}}
