"""RoboForge 2D physics simulator.

A lightweight, dependency-free 2D world with a differential-drive robot,
pushable objects and a goal zone. Enough physics to validate generated
skills (collision, pushing, timeouts) before anything touches real hardware.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class SimObject:
    name: str
    color: str
    x: float
    y: float
    radius: float = 0.30

    def as_dict(self) -> dict:
        return {"name": self.name, "color": self.color,
                "x": round(self.x, 3), "y": round(self.y, 3)}


@dataclass
class Obstacle:
    name: str
    x: float
    y: float
    radius: float


@dataclass
class GoalZone:
    x: float
    y: float
    radius: float = 1.0


@dataclass
class World:
    """Simulation state. Units: meters / degrees / seconds."""

    width: float = 10.0
    height: float = 10.0
    robot_x: float = 1.0
    robot_y: float = 1.0
    robot_theta: float = 0.0  # degrees, 0 = facing +x
    robot_radius: float = 0.35
    carrying: str | None = None
    objects: list[SimObject] = field(default_factory=list)
    obstacles: list[Obstacle] = field(default_factory=list)
    goal: GoalZone | None = None

    # hard limits; SafetyLayer enforces them before the sim ever sees a value
    max_linear_speed: float = 2.0   # m/s
    max_angular_speed: float = 90.0  # deg/s
    dt: float = 0.1


class CollisionError(RuntimeError):
    """The robot hit a wall or a static obstacle."""


class Simulator:
    def __init__(self, world: World):
        self.world = world
        self.time = 0.0
        self.collision_count = 0

    # -------------------------------------------------- physics
    def step(self, linear: float, angular: float) -> None:
        """Advance one tick. Velocities are clamped to world limits."""
        w = self.world
        linear = max(-w.max_linear_speed, min(w.max_linear_speed, linear))
        angular = max(-w.max_angular_speed, min(w.max_angular_speed, angular))

        w.robot_theta = (w.robot_theta + angular * w.dt) % 360.0
        rad = math.radians(w.robot_theta)
        nx = w.robot_x + linear * math.cos(rad) * w.dt
        ny = w.robot_y + linear * math.sin(rad) * w.dt

        if not (w.robot_radius <= nx <= w.width - w.robot_radius
                and w.robot_radius <= ny <= w.height - w.robot_radius):
            self.collision_count += 1
            raise CollisionError(f"hit wall at ({nx:.2f}, {ny:.2f})")

        for ob in w.obstacles:
            if math.hypot(nx - ob.x, ny - ob.y) < ob.radius + w.robot_radius:
                self.collision_count += 1
                raise CollisionError(f"hit obstacle '{ob.name}' at ({nx:.2f}, {ny:.2f})")

        w.robot_x, w.robot_y = nx, ny
        self._resolve_objects()
        self.time += w.dt

    def _resolve_objects(self) -> None:
        """Carried objects follow the robot; loose objects get pushed away."""
        w = self.world
        for obj in w.objects:
            if w.carrying == obj.name:
                obj.x, obj.y = w.robot_x, w.robot_y
                continue
            dx, dy = obj.x - w.robot_x, obj.y - w.robot_y
            d = math.hypot(dx, dy)
            min_d = obj.radius + w.robot_radius
            if 0.0 < d < min_d:
                push = min_d - d
                obj.x += dx / d * push
                obj.y += dy / d * push

    # -------------------------------------------------- helpers
    def render_ascii(self) -> str:
        """ASCII top-down map for logs and headless runs."""
        w = self.world
        cols, rows = 40, 20
        sx, sy = cols / w.width, rows / w.height
        grid = [["."] * cols for _ in range(rows)]

        def put(x: float, y: float, ch: str) -> None:
            cx, cy = int(x * sx), int(y * sy)
            if 0 <= cx < cols and 0 <= cy < rows:
                grid[rows - 1 - cy][cx] = ch

        for ob in w.obstacles:
            put(ob.x, ob.y, "#")
        if w.goal:
            put(w.goal.x, w.goal.y, "G")
        for obj in w.objects:
            put(obj.x, obj.y, obj.name[0].upper())
        put(w.robot_x, w.robot_y, "R")
        border = "+" + "-" * cols + "+"
        return "\n".join([border] + ["|" + "".join(r) + "|" for r in grid] + [border])
