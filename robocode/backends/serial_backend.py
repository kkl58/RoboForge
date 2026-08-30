"""Serial backend (USB / UART / Bluetooth-serial) — Arduino, ESP32, STM32, ...

Talks RHP1 JSON-lines (see firmware/PROTOCOL.md). The transport is
pluggable: hand it a real pyserial port, or any object with
read(len) -> bytes / write(bytes) / timeout — which is what the test
suite uses to run a fake firmware device for conformance checks.

pyserial is an OPTIONAL dependency: only needed for real ports.
"""

from __future__ import annotations

import json
import time


class SerialBackend:
    dt = 0.05  # control period on the PC side; firmware runs its own loop

    def __init__(self, port=None, baudrate: int = 115200, timeout: float = 1.0):
        if port is None or isinstance(port, (str, int)):
            import serial  # optional dependency (pyserial)
            self._io = serial.Serial(port, baudrate, timeout=timeout)
        else:
            self._io = port  # injected transport (tests / custom links)
        self._cmd = (0.0, 0.0)
        self._error: str | None = None
        self._handshake = self._request({"cmd": "ping"})
        if not (self._handshake or {}).get("ok"):
            raise ConnectionError(f"robot did not answer ping: {self._handshake}")

    # ------------------------------------------------------------------ low level
    def _request(self, payload: dict, retries: int = 2) -> dict:
        for attempt in range(retries + 1):
            try:
                self._io.write((json.dumps(payload) + "\n").encode())
                line = self._readline()
                if line:
                    reply = json.loads(line)
                    if not reply.get("ok", False):
                        self._error = reply.get("error", "unknown firmware error")
                    return reply
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                self._error = f"transport: {exc}"
            time.sleep(0.02)
        return {"ok": False, "error": f"no reply after {retries + 1} attempts"}

    def _readline(self) -> str:
        buf = bytearray()
        deadline = time.time() + 1.0
        while time.time() < deadline:
            chunk = self._io.read(64)
            if chunk:
                buf.extend(chunk)
                if b"\n" in chunk:
                    return buf.split(b"\n")[0].decode(errors="replace").strip()
        return ""

    # ------------------------------------------------------------------ HAL contract
    def get_pose(self) -> dict:
        reply = self._request({"cmd": "pose"})
        pose = reply.get("pose") or {"x": 0.0, "y": 0.0, "theta_deg": 0.0}
        return {"x": float(pose["x"]), "y": float(pose["y"]),
                "theta_deg": float(pose["theta_deg"])}

    def get_objects(self) -> list[dict]:
        reply = self._request({"cmd": "objects"})
        return reply.get("objects") or []

    def set_velocity(self, linear: float, angular: float) -> None:
        self._cmd = (linear, angular)
        self._request({"cmd": "vel", "l": round(float(linear), 3),
                       "a": round(float(angular), 2)})

    def tick(self) -> None:
        # the firmware runs its own control loop; on the PC side we simply
        # advance the clock. Velocities stay latched on the device.
        time.sleep(self.dt)

    def grab(self, name: str) -> bool:
        reply = self._request({"cmd": "grab", "name": name})
        return bool(reply.get("grabbed", False))

    def release(self) -> bool:
        reply = self._request({"cmd": "release"})
        return bool(reply.get("ok", False))

    def get_carrying(self) -> str | None:
        reply = self._request({"cmd": "carrying"})
        return reply.get("carrying")

    def stop(self) -> None:
        self._cmd = (0.0, 0.0)
        self._request({"cmd": "stop"})

    def pop_error(self) -> str | None:
        err, self._error = self._error, None
        return err

    def get_scene(self) -> dict:
        pose = self.get_pose()
        return {"world_size": None, "robot": pose,
                "objects": self.get_objects(), "goal": None}
