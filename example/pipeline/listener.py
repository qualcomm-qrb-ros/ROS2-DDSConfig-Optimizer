#!/usr/bin/env python3
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Listener node: subscribes to /chatter and counts received messages.

Pure rclpy so it runs without a colcon build. The ros2_benchmark MonitorNode
does the actual latency/throughput measurement; this node just provides a
realistic subscriber on the topic and logs receipt counts.
"""
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Header


class Listener(Node):
    def __init__(self):
        super().__init__('listener')
        self.declare_parameter('reliable', True)
        reliable = self.get_parameter('reliable').value

        qos = QoSProfile(depth=10)
        qos.reliability = (
            ReliabilityPolicy.RELIABLE if reliable else ReliabilityPolicy.BEST_EFFORT
        )
        self._count = 0
        self._sub = self.create_subscription(Header, '/chatter', self._on_msg, qos)
        self.get_logger().info(f'Listener started: reliable={reliable}, topic=/chatter')

    def _on_msg(self, msg: Header):
        self._count += 1
        if self._count % 50 == 0:
            self.get_logger().info(
                f'Received {self._count} messages (last frame_id={msg.frame_id})'
            )


def main(args=None):
    rclpy.init(args=args)
    node = Listener()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
