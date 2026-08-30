"""HTTP/WiFi backend — ESP32-style robots that expose a REST control API.

Same RHP1 semantics as the serial backend, over HTTP (see
firmware/PROTOCOL.md). Works with the reference ESP32 firmware in
firmware/esp32_http_server.ino or any robot implementing the routes.
"""

from __future__ import annotations

import json
import time
import urllib.request


class HttpBackend:
    dt = 0.05

    def __init__(self, base_url: str, timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._error: str | None = None
        handshake = self._request("GET", "/ping")
        if not handshake.get("ok"):
            raise ConnectionError(f"robot did not answer ping at {self.base_url}: {handshake}")

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    self.base_url + path,
                    data=json.dumps(body).encode() if body is not None else None,
                    method=method,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    reply = json.loads(resp.read().decode())
                if not reply.get("ok", False):
                    self._error = reply.get("error", "unknown robot error")
                return reply
            except (OSError, json.JSONDecodeError) as exc:
                self._error = f"transport: {exc}"
                time.sleep(0.05 * (attempt + 1))
        return {"ok": False, "error": "unreachable"}

    # ------------------------------------------------------------------ HAL contract
    def get_pose(self) -> dict:
        pose = self._request("GET", "/pose").get("pose") or {}
        return {"x": float(pose.get("x", 0.0)), "y": float(pose.get("y", 0.0)),
                "theta_deg": float(pose.get("theta_deg", 0.0))}

    def get_objects(self) -> list[dict]:
        return self._request("GET", "/objects").get("objects") or []

    def set_velocity(self, linear: float, angular: float) -> None:
        self._request("POST", "/vel", {"l": round(float(linear), 3),
                                       "a": round(float(angular), 2)})

    def tick(self) -> None:
        time.sleep(self.dt)

    def grab(self, name: str) -> bool:
        return bool(self._request("POST", "/grab", {"name": name}).get("grabbed", False))

    def release(self) -> bool:
        return bool(self._request("POST", "/release").get("ok", False))

    def get_carrying(self) -> str | None:
        return self._request("GET", "/carrying").get("carrying")

    def stop(self) -> None:
        self._request("POST", "/stop")

    def pop_error(self) -> str | None:
        err, self._error = self._error, None
        return err

    def get_scene(self) -> dict:
        return {"world_size": None, "robot": self.get_pose(),
                "objects": self.get_objects(), "goal": None}
