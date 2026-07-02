#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Talker node: publishes std_msgs/msg/Header on /chatter at a fixed rate.

Each message carries header.stamp = publish time (used for end-to-end latency
measurement by the ros2_benchmark MonitorNode) and header.frame_id = an
incrementing counter. Pure rclpy so it runs without a colcon build.
"""
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header


class Talker(Node):
    def __init__(self):
        super().__init__('talker')
        self.declare_parameter('publish_rate_hz', 10.0)
        self.declare_parameter('reliable', True)
        rate = self.get_parameter('publish_rate_hz').value
        reliable = self.get_parameter('reliable').value

        qos = QoSProfile(depth=10)
        qos.reliability = (
            ReliabilityPolicy.RELIABLE if reliable else ReliabilityPolicy.BEST_EFFORT
        )
        self._pub = self.create_publisher(Header, '/chatter', qos)
        self._counter = 0
        self._timer = self.create_timer(1.0 / rate, self._tick)
        self.get_logger().info(
            f'Talker started: {rate} Hz, reliable={reliable}, topic=/chatter'
        )

    def _tick(self):
        msg = Header()
        msg.stamp = self.get_clock().now().to_msg()
        msg.frame_id = str(self._counter)
        self._pub.publish(msg)
        self._counter += 1


def main(args=None):
    # A SIGINT/SIGTERM from launch_test (or a plain Ctrl-C) surfaces as
    # KeyboardInterrupt or ExternalShutdownException. Catch both so the node
    # shuts down cleanly and exits 0 instead of dumping a traceback.
    rclpy.init(args=args)
    node = Talker()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
