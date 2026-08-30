"""The RobotAPI: the ONLY surface generated code is allowed to touch.

Every method goes through the SafetyLayer, then the HardwareBackend —
a simulation, a serial MCU, a WiFi robot or a ROS 2 stack. Generated
skills are identical across all of them; the backend is the only thing
that changes between sim and reality.
"""

from __future__ import annotations

import math
import time

from .safety import SafetyLayer, SafetyViolation

API_REFERENCE = """\
class RobotAPI  # every generated skill receives `robot: RobotAPI`
    get_position() -> dict
        {"x": float, "y": float, "theta_deg": float}  # 0 deg = facing +x
    sense_objects() -> list[dict]
        [{"name": "red_box", "color": "red", "x": 3.0, "y": 2.0}, ...]
        whatever the perception stack sees (sim: perfect; real: camera/VLM).
    move_to(x: float, y: float, timeout_s: float = 30.0) -> bool
        Drive to (x, y). Blocks until arrival or timeout.
        Returns True on arrival. Raises SafetyViolation on illegal targets.
    turn_to(theta_deg: float) -> bool
        Rotate in place to face the given absolute heading.
    face(x: float, y: float) -> bool
        Rotate in place to face the point (x, y).
    grab(object_name: str) -> bool
        Attach the named object if within reach of the gripper.
    release() -> bool
        Drop whatever is being carried.
    get_carrying() -> str | None
    stop() -> None
        Immediate stop.
    log(message) / print(...)   progress lines are shown to the operator

Speeds and targets are capped by a hard safety layer; violations raise
SafetyViolation and abort the skill.
"""


class RobotAPI:
    def __init__(self, backend, safety: SafetyLayer):
        self.backend = backend
        self.safety = safety
        self.call_log: list[str] = []

    # -------------------------------------------------- perception
    def get_position(self) -> dict:
        return self.backend.get_pose()

    def sense_objects(self) -> list[dict]:
        return self.backend.get_objects()

    # -------------------------------------------------- motion
    def _tick(self) -> bool:
        """Advance one control step. Returns False on a backend fault."""
        self.backend.tick()
        err = self.backend.pop_error()
        if err:
            self.backend.stop()
            self.call_log.append(f"[fault] {err}")
            return False
        return True

    def move_to(self, x: float, y: float, timeout_s: float = 30.0) -> bool:
        self.safety.check_target(float(x), float(y))
        started_at = time.monotonic()
        cruise = 0.8  # m/s
        while True:
            self.safety.check_episode_elapsed(time.monotonic() - started_at)
            pose = self.backend.get_pose()
            dx, dy = float(x) - pose["x"], float(y) - pose["y"]
            dist = math.hypot(dx, dy)
            if dist < 0.15:
                self.stop()
                return True
            if time.monotonic() - started_at > timeout_s:
                self.stop()
                return False
            self.face(x, y)
            v = cruise if dist > 1.0 else max(0.25, dist)
            self.backend.set_velocity(v, 0.0)
            if not self._tick():
                return False

    def turn_to(self, theta_deg: float, timeout_s: float = 15.0) -> bool:
        """Rotate in place with a self-tuning gain.

        The PC cannot assume how much the body rotates per control tick —
        firmware runs its own loop (a sim advances one fixed dt, an MCU
        may tick 10x faster). So each iteration measures the actual
        response to the previous command and rescales: the commanded
        velocity targets ~70% of the remaining error per cycle, which
        converges on any body that roughly obeys its velocity commands.
        """
        target = float(theta_deg) % 360.0
        started_at = time.monotonic()
        rate = None       # measured: deg rotated per (deg/s commanded * second)
        last_w = 0.0
        last_dt = self.backend.dt
        last_pose = self.backend.get_pose()["theta_deg"]
        stuck = 0

        while True:
            self.safety.check_episode_elapsed(time.monotonic() - started_at)
            pose = self.backend.get_pose()
            diff = (target - pose["theta_deg"] + 180.0) % 360.0 - 180.0
            if abs(diff) < 2.0:
                self.stop()
                return True
            if time.monotonic() - started_at > timeout_s:
                self.stop()
                return False

            # update response-rate estimate from the previous command
            rotated = (pose["theta_deg"] - last_pose + 180.0) % 360.0 - 180.0
            if abs(last_w) > 1e-3 and last_dt > 1e-3:
                measured = abs(rotated) / (abs(last_w) * last_dt)
                if measured > 1e-3:
                    rate = measured if rate is None else 0.5 * rate + 0.5 * measured
                stuck = stuck + 1 if abs(rotated) < 1e-6 else 0
                if stuck > 25:
                    self.stop()
                    return False  # wheels not responding at all
            last_pose = pose["theta_deg"]

            if rate:
                w = diff * 0.7 / (rate * self.backend.dt)
            else:
                w = diff / 0.15
            w = max(-45.0, min(45.0, w))
            t_cmd = time.monotonic()
            self.backend.set_velocity(0.0, w)
            if not self._tick():
                return False
            last_w = w
            last_dt = max(1e-3, time.monotonic() - t_cmd)

    def face(self, x: float, y: float) -> bool:
        pose = self.backend.get_pose()
        target = math.degrees(math.atan2(float(y) - pose["y"],
                                         float(x) - pose["x"])) % 360.0
        return self.turn_to(target)

    # -------------------------------------------------- manipulation
    def grab(self, object_name: str) -> bool:
        return bool(self.backend.grab(object_name))

    def release(self) -> bool:
        return bool(self.backend.release())

    def get_carrying(self) -> str | None:
        return self.backend.get_carrying()

    # -------------------------------------------------- misc
    def stop(self) -> None:
        self.backend.stop()

    def log(self, message: str) -> None:
        self.call_log.append(str(message))
