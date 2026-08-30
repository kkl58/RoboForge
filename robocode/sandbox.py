"""Sandbox: run model-generated code with nothing but the robot API.

The generated skill is a function `run(robot)`. We exec it with a minimal
global namespace: `math`, `time`, and `robot`. No imports, no I/O, no
attributes outside the API — and a watchdog thread kills runaway code.
"""

from __future__ import annotations

import builtins
import threading

from .robot_api import RobotAPI

_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
        "len", "list", "max", "min", "print", "range", "round", "set",
        "sorted", "str", "sum", "tuple", "zip", "True", "False", "None",
    )
}

# Generated code gets a proxy exposing ONLY these — it must never reach the
# simulator internals or the safety layer (robot.sim.world.robot_x = 999 …).
_ALLOWED_METHODS = frozenset({
    "get_position", "sense_objects", "move_to", "turn_to", "face",
    "grab", "release", "get_carrying", "stop", "log",
})

# print() inside generated skills resolves through this custom builtins
# entry — we must NOT use contextlib.redirect_stdout around exec(): a
# spinning daemon thread + stdout redirection can silently kill the whole
# interpreter (observed on CPython 3.13 / Windows), which would take down
# the robot's brain with it.
_MAX_CAPTURED_LINES = 500


def _make_capture_print(buffer: list) -> callable:
    def capture_print(*args, **kwargs):
        if len(buffer) < _MAX_CAPTURED_LINES:
            buffer.append(" ".join(str(a) for a in args))
    return capture_print


class RobotProxy:
    """Whitelist facade handed to generated skills.

    Uses __getattribute__ (not __getattr__): underscore/dunder names like
    _api, __class__ or __dict__ resolve through normal lookup and would
    bypass __getattr__ entirely — and __init__.__globals__ is the classic
    sandbox escape to the real builtins.
    """

    def __init__(self, api: RobotAPI):
        object.__setattr__(self, "_api", api)

    def __setattr__(self, name: str, value) -> None:
        raise AttributeError("generated skills may not set attributes on the robot proxy")

    def __getattribute__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(
                f"generated skills may not access '{name}' (underscore/dunder "
                "attributes are the sandbox-escape hatch)")
        if name in _ALLOWED_METHODS:
            return getattr(object.__getattribute__(self, "_api"), name)
        raise AttributeError(
            f"generated skills may only use RobotAPI methods {sorted(_ALLOWED_METHODS)}; "
            f"'{name}' is not allowed")


class SandboxTimeout(RuntimeError):
    pass


class SandboxError(RuntimeError):
    pass


def extract_code(model_output: str) -> str:
    """Pull the python payload out of a raw LLM response."""
    text = model_output.strip()
    if "```" in text:
        chunks = text.split("```")
        for chunk in chunks[1::2]:
            body = chunk.strip()
            if body.startswith("python"):
                body = body[6:].strip()
            if "def run(" in body:
                return body
        raise SandboxError("model returned a code block without `def run(robot)`")
    if "def run(" not in text:
        raise SandboxError("model output does not contain `def run(robot)`")
    return text


def run_skill(code: str, robot: RobotAPI, timeout_s: float = 60.0) -> dict:
    """Execute `run(robot)` in a restricted namespace. Returns a report."""
    import math
    import time

    result: dict = {"ok": False, "error": None, "output": []}
    captured: list[str] = []

    def target() -> None:
        sandbox_builtins = dict(_SAFE_BUILTINS)
        sandbox_builtins["print"] = _make_capture_print(captured)
        sandbox_globals = {"__builtins__": sandbox_builtins,
                           "math": math, "time": time,
                           "robot": RobotProxy(robot)}
        try:
            exec(compile(code, "<generated-skill>", "exec"), sandbox_globals)  # noqa: S102
            sandbox_globals["run"](sandbox_globals["robot"])
            result["ok"] = True
        except BaseException as exc:  # noqa: BLE001 — report anything back to the LLM
            result["error"] = f"{type(exc).__name__}: {exc}"
        result["output"] = captured[-20:]

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        raise SandboxTimeout(f"generated skill exceeded {timeout_s}s — terminated")
    return result
