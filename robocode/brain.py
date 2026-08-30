"""Brain: the orchestrator.

Pipeline for every task:
  1. skill library lookup  -> hit?  replay it, done
  2. no hit -> LLM writes a skill (retry with the error as feedback)
  3. sandbox execution on the backend (sim: fresh world per attempt;
     real hardware: same robot, faults are contained by the safety layer)
  4. success check -> verified skills go back into the library

Nothing in here trusts the model: every call is sandboxed, every motion is
safety-checked, and only verified skills are ever reused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .codegen import CodeGen
from .robot_api import RobotAPI
from .safety import SafetyLayer
from .sandbox import SandboxError, SandboxTimeout, extract_code, run_skill


@dataclass
class Task:
    text: str
    backend_factory: Callable[[], object]   # fresh sim world per attempt; same robot for real HW
    success_check: Callable[[object], bool] # fn(backend) -> bool
    safety: SafetyLayer | None = None
    max_attempts: int = 3


@dataclass
class TaskResult:
    task: str
    success: bool
    attempts: int
    source: str = "failed"
    skill_id: str | None = None
    log: list[str] = field(default_factory=list)
    backend: object | None = None   # final backend state, for maps / inspection


class Brain:
    def __init__(self, codegen: CodeGen, skill_library, verbose: bool = True):
        self.codegen = codegen
        self.library = skill_library
        self.verbose = verbose

    def _say(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    # ------------------------------------------------------------------
    def run(self, task: Task) -> TaskResult:
        self._say(f"\n=== Task: {task.text} ===")

        cached = self.library.find(task.text)
        if cached:
            self._say(f"[brain] skill library hit: {cached['id']} — replaying")
            backend = task.backend_factory()
            ok = self._execute(cached["code"], task, backend)
            if ok:
                self.library.record_use(cached["id"])
                return TaskResult(task.text, True, 1, "library", cached["id"],
                                  backend=backend)
            self._say("[brain] replay failed, falling back to live codegen")

        feedback = ""
        for attempt in range(1, task.max_attempts + 1):
            self._say(f"[brain] attempt {attempt}: asking the model to write a skill...")
            scene = task.backend_factory().get_scene()
            raw = self.codegen.generate(task.text, scene, feedback)
            try:
                code = extract_code(raw)
            except SandboxError as exc:
                feedback = str(exc)
                self._say(f"[brain] unparseable output: {feedback}")
                continue

            backend = task.backend_factory()
            ok, error = self._execute_with_feedback(code, task, backend)
            if ok:
                entry = self.library.save(task.text, code, verified=True,
                                          source=self.codegen.provider)
                self._say(f"[brain] verified and saved as {entry['id']}")
                return TaskResult(task.text, True, attempt,
                                  self.codegen.provider, entry["id"], backend=backend)
            feedback = error or "skill finished without meeting the success condition"
            self._say(f"[brain] attempt {attempt} failed: {feedback}")

        return TaskResult(task.text, False, task.max_attempts, "failed")

    # ------------------------------------------------------------------
    def _execute_with_feedback(self, code: str, task: Task, backend) -> tuple[bool, str | None]:
        safety = task.safety or SafetyLayer(getattr(backend, "world", None)
                                            and (backend.world.width, backend.world.height))
        robot = RobotAPI(backend, safety)
        try:
            report = run_skill(code, robot)
        except (SandboxTimeout, SandboxError) as exc:
            return False, str(exc)

        if report["error"]:
            return False, report["error"]

        for line in report["output"]:
            self._say(f"  [skill] {line}")
        for msg in robot.call_log:
            self._say(f"  [skill] {msg}")

        if task.success_check(backend):
            self._say("[brain] success check PASSED")
            return True, None
        return False, None

    def _execute(self, code: str, task: Task, backend) -> bool:
        ok, _ = self._execute_with_feedback(code, task, backend)
        return ok
