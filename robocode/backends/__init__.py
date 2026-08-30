"""Hardware abstraction layer (HAL).

A HardwareBackend is everything RobotAPI needs to drive ANY robot:
a simulation, a serial MCU, a WiFi robot, a ROS 2 stack, ...

Contract (all backends MUST satisfy it, enforced by the conformance
suite in tests/test_backends.py):

  get_pose()      -> {"x", "y", "theta_deg"}          robot pose in meters/deg
  get_objects()   -> [{"name","color","x","y"}]       perceived scene
  set_velocity(l, a)                                  l m/s, a deg/s (latched)
  tick()                                              advance one control step
  grab(name) -> bool                                  attach object within range
  release()  -> bool
  get_carrying() -> str | None
  stop()                                              zero motion NOW
  pop_error() -> str | None                           last fault, if any
"""

from __future__ import annotations

from .http_backend import HttpBackend
from .ros2_backend import Ros2Backend
from .serial_backend import SerialBackend
from .sim_backend import SimBackend

BACKENDS: dict[str, type] = {
    "sim": SimBackend,
    "serial": SerialBackend,
    "http": HttpBackend,
    "ros2": Ros2Backend,
}


def register(name: str, cls: type) -> None:
    BACKENDS[name] = cls


def make_backend(config: dict):
    """Build a backend from a config dict: {"type": "serial", "port": ...}."""
    btype = config.get("type", "sim")
    if btype not in BACKENDS:
        raise ValueError(f"unknown backend type '{btype}'. Available: {sorted(BACKENDS)}")
    return BACKENDS[btype](**{k: v for k, v in config.items() if k != "type"})
