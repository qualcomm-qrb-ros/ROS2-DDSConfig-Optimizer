# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear
"""Live end-to-end benchmark for the talker/listener rclpy pipeline.

Pipeline under test (LIVE mode, nodes generate their own data):
    talker  -> /chatter (std_msgs/msg/Header @ 10 Hz) -> listener
A ros2_benchmark MonitorNode also subscribes to /chatter to measure
end-to-end latency (header.stamp -> receipt) and throughput.

Run:  launch_test chatter_benchmark.py
"""
import os

from launch.actions import ExecuteProcess
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

from ros2_benchmark import (
    ROS2BenchmarkConfig,
    ROS2BenchmarkTest,
    BasicPerformanceCalculator,
    BenchmarkMode,
    MonitorPerformanceCalculatorsInfo,
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def launch_setup(container_prefix, container_sigterm_timeout):
    # Talker / Listener as plain rclpy nodes (no colcon build needed).
    talker = ExecuteProcess(
        cmd=['python3', os.path.join(_THIS_DIR, 'talker.py')],
        output='screen',
    )
    listener = ExecuteProcess(
        cmd=['python3', os.path.join(_THIS_DIR, 'listener.py')],
        output='screen',
    )

    # MonitorNode (C++ composable) measures /chatter latency + throughput.
    monitor_container = ComposableNodeContainer(
        name='monitor_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container_mt',
        prefix=container_prefix,
        sigterm_timeout=container_sigterm_timeout,
        composable_node_descriptions=[
            ComposableNode(
                name='MonitorNode',
                namespace=TestChatterPipeline.generate_namespace(),
                package='ros2_benchmark',
                plugin='ros2_benchmark::MonitorNode',
                parameters=[{
                    'monitor_index': 0,
                    'monitor_data_format': 'std_msgs/msg/Header',
                }],
                remappings=[('output', '/chatter')],
            ),
        ],
        output='screen',
    )

    return [talker, listener, monitor_container]


def generate_test_description():
    return TestChatterPipeline.generate_test_description_with_nsys(launch_setup)


class TestChatterPipeline(ROS2BenchmarkTest):
    """Live E2E benchmark for the talker -> /chatter -> listener pipeline."""

    config = ROS2BenchmarkConfig(
        benchmark_name='Talker/Listener Chatter Pipeline E2E Benchmark',
        benchmark_mode=BenchmarkMode.LIVE,
        benchmark_duration=10,
        test_iterations=5,
        collect_start_timestamps_from_monitors=True,
        monitor_info_list=[
            MonitorPerformanceCalculatorsInfo(
                'monitor_node0',
                [BasicPerformanceCalculator({
                    'report_prefix': 'chatter_pipeline',
                    'message_key_match': True,
                })],
            )
        ],
        custom_report_info={
            'pipeline': 'talker-listener',
            'topic': '/chatter',
            'message_type': 'std_msgs/msg/Header',
            'publish_rate_hz': 10.0,
        },
    )

    def test_benchmark(self):
        self.run_benchmark()
