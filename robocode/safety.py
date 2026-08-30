"""Hard-coded safety layer. Generated code can NEVER bypass this.

Every robot API call passes through here before reaching the hardware
backend. Limits are plain constants on purpose: no model output, no
config file, nothing the LLM writes can change them. On real hardware
this is the second line of defense — firmware limits and e-stops are
the first and must never be skipped.

Bounds are optional: a simulated warehouse is 10x10 m, a real robot
roams wherever its operators decided.
"""

from __future__ import annotations

import math

MAX_LINEAR_SPEED = 1.5       # m/s
MAX_ANGULAR_SPEED = 60.0     # deg/s
MAX_EPISODE_SECONDS = 120.0  # one skill run may never exceed this
FORBIDDEN_ZONES: list[tuple[float, float, float]] = []  # (x, y, radius) no-go areas


class SafetyViolation(RuntimeError):
    """A generated action tried to exceed a hard limit."""


class SafetyLayer:
    def __init__(self, bounds: tuple[float, float] | None = None):
        self.bounds = bounds

    def check_speeds(self, linear: float, angular: float) -> tuple[float, float]:
        lin = max(-MAX_LINEAR_SPEED, min(MAX_LINEAR_SPEED, linear))
        ang = max(-MAX_ANGULAR_SPEED, min(MAX_ANGULAR_SPEED, angular))
        if lin != linear or ang != angular:
            raise SafetyViolation(
                f"requested speed ({linear:.2f} m/s, {angular:.1f} deg/s) "
                f"exceeds limits ({MAX_LINEAR_SPEED}, {MAX_ANGULAR_SPEED})")
        return lin, ang

    def check_target(self, x: float, y: float) -> None:
        if not (math.isfinite(x) and math.isfinite(y)):
            raise SafetyViolation(f"target ({x}, {y}) is not a finite number")
        if self.bounds is not None:
            bx, by = self.bounds
            if not (0 <= x <= bx and 0 <= y <= by):
                raise SafetyViolation(
                    f"target ({x:.2f}, {y:.2f}) is outside the {bx}x{by} work area")
        for zx, zy, zr in FORBIDDEN_ZONES:
            if math.hypot(x - zx, y - zy) < zr:
                raise SafetyViolation(f"target ({x:.2f}, {y:.2f}) is inside a forbidden zone")

    def check_episode_elapsed(self, elapsed: float) -> None:
        if elapsed > MAX_EPISODE_SECONDS:
            raise SafetyViolation(
                f"episode ran {elapsed:.1f}s, over the {MAX_EPISODE_SECONDS}s cap")
