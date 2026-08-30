"""ROS 2 backend — for TurtleBot-style stacks and industrial robots.

Publishes /cmd_vel (geometry_msgs/Twist), subscribes /odom for pose.
Perception comes from whatever you bridge into the `objects` parameter.

rclpy is OPTIONAL: the import happens lazily so the rest of RoboForge
works without a ROS installation. Angles: ROS yaw (rad, CCW) ↔ our
theta_deg (deg, CCW) convert directly.
"""

from __future__ import annotations

import math
import threading


class Ros2Backend:
    dt = 0.05

    def __init__(self, cmd_topic: str = "/cmd_vel", odom_topic: str = "/odom"):
        import rclpy  # optional dependency — raises ImportError with a clear origin
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry

        rclpy.init()
        self._node = rclpy.create_node("roboforge_backend")
        self._pub = self._node.create_publisher(Twist, cmd_topic, 10)
        self._pose = {"x": 0.0, "y": 0.0, "theta_deg": 0.0}
        self._lock = threading.Lock()
        self._error: str | None = None
        self._objects: list[dict] = []
        self._carrying: str | None = None

        def on_odom(msg: Odometry) -> None:
            p = msg.pose.pose.position
            yaw = math.atan2(
                2.0 * (msg.pose.pose.orientation.w * msg.pose.pose.orientation.z
                       + msg.pose.pose.orientation.x * msg.pose.pose.orientation.y),
                1.0 - 2.0 * (msg.pose.pose.orientation.y ** 2 + msg.pose.pose.orientation.z ** 2))
            with self._lock:
                self._pose = {"x": float(p.x), "y": float(p.y),
                              "theta_deg": round(math.degrees(yaw), 2)}

        self._node.create_subscription(Odometry, odom_topic, on_odom, 10)

    # ------------------------------------------------------------------
    def set_objects(self, objects: list[dict]) -> None:
        """Feed external perception (VLM, lidar clustering...) into the HAL."""
        self._objects = objects

    def _spin_once(self) -> None:
        import rclpy
        rclpy.spin_once(self._node, timeout_sec=0.0)

    # ------------------------------------------------------------------ HAL contract
    def get_pose(self) -> dict:
        self._spin_once()
        with self._lock:
            return dict(self._pose)

    def get_objects(self) -> list[dict]:
        return list(self._objects)

    def set_velocity(self, linear: float, angular: float) -> None:
        from geometry_msgs.msg import Twist
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = math.radians(float(angular))
        self._pub.publish(msg)

    def tick(self) -> None:
        import time
        self._spin_once()
        time.sleep(self.dt)

    def grab(self, name: str) -> bool:
        self._error = "grab: attach a manipulation service to this backend"
        return False

    def release(self) -> bool:
        self._error = "release: attach a manipulation service to this backend"
        return False

    def get_carrying(self) -> str | None:
        return self._carrying

    def stop(self) -> None:
        self.set_velocity(0.0, 0.0)

    def pop_error(self) -> str | None:
        err, self._error = self._error, None
        return err

    def get_scene(self) -> dict:
        return {"world_size": None, "robot": self.get_pose(),
                "objects": self.get_objects(), "goal": None}
