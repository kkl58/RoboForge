"""Simulation backend — the reference implementation of HardwareBackend.

Wraps the existing 2D simulator so the whole stack (safety, sandbox,
codegen, brain) runs identically in sim and on real hardware.
"""

from __future__ import annotations

import math

from ..simulator import Simulator, World


class SimBackend:
    dt = 0.1

    def __init__(self, world: World | None = None):
        self.world = world or World()
        self._sim = Simulator(self.world)
        self._cmd = (0.0, 0.0)
        self._error: str | None = None

    # ------------------------------------------------------------------
    def get_pose(self) -> dict:
        w = self.world
        return {"x": round(w.robot_x, 4), "y": round(w.robot_y, 4),
                "theta_deg": round(w.robot_theta, 2)}

    def get_objects(self) -> list[dict]:
        return [o.as_dict() for o in self.world.objects]

    def set_velocity(self, linear: float, angular: float) -> None:
        self._cmd = (linear, angular)

    def tick(self) -> None:
        try:
            self._sim.step(*self._cmd)
            self._error = None
        except Exception as exc:  # CollisionError and anything else
            self._error = f"{type(exc).__name__}: {exc}"
            self._cmd = (0.0, 0.0)

    def grab(self, name: str) -> bool:
        w = self.world
        if w.carrying:
            return False
        for obj in w.objects:
            if obj.name == name:
                d = math.hypot(obj.x - w.robot_x, obj.y - w.robot_y)
                if d <= 0.6 + obj.radius:
                    w.carrying = name
                    return True
                return False
        return False

    def release(self) -> bool:
        self.world.carrying = None
        return True

    def get_carrying(self) -> str | None:
        return self.world.carrying

    def stop(self) -> None:
        self._cmd = (0.0, 0.0)

    def pop_error(self) -> str | None:
        err, self._error = self._error, None
        return err

    def get_scene(self) -> dict:
        w = self.world
        return {
            "world_size": [w.width, w.height],
            "robot": self.get_pose(),
            "objects": self.get_objects(),
            "goal": {"x": w.goal.x, "y": w.goal.y} if w.goal else None,
        }

    def render_map(self) -> str:
        return self._sim.render_ascii()
