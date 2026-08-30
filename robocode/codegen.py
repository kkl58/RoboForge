"""LLM client that writes skills at runtime.

Two providers:
  - "openai": any OpenAI-compatible endpoint (GLM, DeepSeek, vLLM, ...) —
    configure base_url / api_key / model in config.json.
  - "mock":   a built-in canned skill generator so the whole loop runs
    offline with zero API keys. Great for CI and first contact.
"""

from __future__ import annotations

import json
import urllib.request

from .robot_api import API_REFERENCE

SYSTEM_PROMPT = """\
You are the onboard brain of a warehouse robot. You write Python skills that
make the robot complete the user's task using ONLY the RobotAPI below.
Rules:
 - Define exactly one function: `def run(robot):`
 - Call ONLY methods on `robot`. Do not import anything.
 - Never hardcode coordinates you were not given; look them up with
   robot.sense_objects() / robot.get_position().
 - Prefer simple loops. Keep the skill under 60 lines.
 - Print one short line of progress at each major step.

RobotAPI reference:
""" + API_REFERENCE

MOCK_SKILL_TEMPLATE = '''\
def run(robot):
    target = None
    goal = {goal!r}
    for obj in robot.sense_objects():
        if obj["color"] == {color!r}:
            target = obj
            break
    if target is None:
        robot.log("target object not found")
        return
    print("found", target["name"], "at", target["x"], target["y"])
    robot.move_to(target["x"], target["y"])
    if not robot.grab(target["name"]):
        print("grab failed, retrying once")
        robot.move_to(target["x"], target["y"])
        if not robot.grab(target["name"]):
            return
    print("carrying", robot.get_carrying())
    robot.move_to(goal[0], goal[1])
    robot.release()
    print("delivered", target["name"], "to", goal)
'''


class CodeGen:
    def __init__(self, config: dict):
        self.provider = config.get("provider", "mock")
        self.base_url = config.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "glm-5.3-flash")

    # ------------------------------------------------------------------
    def generate(self, task: str, scene: str, feedback: str = "") -> str:
        if self.provider == "mock":
            return self._mock(task, scene)
        prompt = f"Scene:\n{scene}\n\nTask: {task}"
        if feedback:
            prompt += f"\n\nYour previous attempt failed with:\n{feedback}\nWrite a fixed version."
        return self._openai(prompt)

    def _openai(self, prompt: str) -> str:
        req = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    def _mock(self, task: str, scene) -> str:
        """Canned generator for the built-in demo task.

        It 'reads' the scene the same way a real model would and emits a
        generic pick-and-place skill. This exists so the full loop
        (generate -> sandbox -> verify -> execute -> skill library) is
        testable with no network access.
        """
        scene_data = scene if isinstance(scene, dict) else json.loads(scene)
        colors = [o["color"] for o in scene_data.get("objects", [])]
        color = "red" if "red" in colors else (colors[0] if colors else "red")
        goal = scene_data.get("goal") or {"x": 8.0, "y": 8.0}
        if isinstance(goal, dict):
            goal = [goal["x"], goal["y"]]
        return f"```python\n{MOCK_SKILL_TEMPLATE.format(color=color, goal=goal)}\n```"
