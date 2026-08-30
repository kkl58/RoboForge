"""Perception: how the robot "sees" the scene in the real world.

SimBackend answers get_objects() perfectly from the simulator. On real
hardware, perception is an upstream source:

  - SimVision          — pass-through (simulation, tests)
  - StaticMapVision    — operator-fed object table (JSON file / dict):
                         calibrated workspace where things don't move much
  - VLMVision          — a camera frame + a multimodal LLM (GLM / Qwen-VL /
                         any OpenAI-compatible endpoint) returns the object
                         list as JSON. Needs OpenCV for capture (optional).

All of them produce the same [{"name","color","x","y"}] contract.
"""

from __future__ import annotations

import base64
import json
import urllib.request

VLM_SYSTEM_PROMPT = """\
You are the eyes of a warehouse robot on a top-down camera.
Return ONLY a JSON array of visible objects:
[{"name": "red_box", "color": "red", "x": 1.2, "y": 0.5}, ...]
x/y in meters in the robot world frame (origin bottom-left of the
workspace), using the calibration given by the operator. No prose."""


class SimVision:
    def __init__(self, backend):
        self.backend = backend

    def get_objects(self) -> list[dict]:
        return self.backend.get_objects()


class StaticMapVision:
    def __init__(self, objects: list[dict] | str):
        if isinstance(objects, str):
            objects = json.loads(__import__("pathlib").Path(objects).read_text(encoding="utf-8"))
        self._objects = objects

    def get_objects(self) -> list[dict]:
        return list(self._objects)


class VLMVision:
    """Camera frame -> multimodal LLM -> object list.

    calibration maps camera pixels to world meters; pass the mapping in
    `hint` so the model has the operator's anchor points.
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 calibration_hint: str = "", camera_index: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.calibration_hint = calibration_hint
        self._camera_index = camera_index

    def capture_jpeg_b64(self) -> str:
        import cv2  # optional dependency (opencv-python)
        cam = cv2.VideoCapture(self._camera_index)
        ok, frame = cam.read()
        cam.release()
        if not ok:
            raise RuntimeError("camera capture failed")
        import cv2 as _cv2
        ok, jpg = _cv2.imencode(".jpg", frame)
        return base64.b64encode(jpg.tobytes()).decode()

    def get_objects(self) -> list[dict]:
        image_b64 = self.capture_jpeg_b64()
        body = json.dumps({
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text":
                        VLM_SYSTEM_PROMPT + f"\nCalibration: {self.calibration_hint}"},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            "temperature": 0.0,
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            content = json.loads(resp.read().decode())["choices"][0]["message"]["content"]
        start, end = content.find("["), content.rfind("]") + 1
        objects = json.loads(content[start:end])
        for obj in objects:
            obj["x"], obj["y"] = float(obj["x"]), float(obj["y"])
        return objects


class VisionBackendAdapter:
    """Wrap a backend + an external vision source into one HAL view.

    The RobotAPI reads objects through this; pose/motion stay on the
    backend. Used in chat mode so skills see the real perception.
    """

    def __init__(self, backend, vision):
        self._backend = backend
        self._vision = vision

    def __getattr__(self, name):
        return getattr(self._backend, name)

    def get_objects(self) -> list[dict]:
        return self._vision.get_objects()

    def get_scene(self) -> dict:
        return {"world_size": None, "robot": self._backend.get_pose(),
                "objects": self._vision.get_objects(), "goal": None}
