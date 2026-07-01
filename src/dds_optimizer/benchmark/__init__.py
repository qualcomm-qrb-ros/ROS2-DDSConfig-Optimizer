# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Benchmark module: runs ros2_benchmark tests and parses results.

Components:
- launcher: Runs 'launch_test benchmark.py' with the FastDDS config set
- results_parser: Parses the JSON output from ros2_benchmark

ros2_benchmark output format:
    The benchmark writes results to a JSON file at:
    {ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER}/{ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME}.json

    Key metrics extracted:
    - BasicPerformanceMetrics.FIRST_SENT_RECEIVED_LATENCY (ms)
    - BasicPerformanceMetrics.LAST_SENT_RECEIVED_LATENCY (ms)
    - BasicPerformanceMetrics.MEAN_FRAME_RATE (fps = msgs/sec)
    - BasicPerformanceMetrics.NUM_MISSED_FRAMES
    - BasicPerformanceMetrics.NUM_FRAMES_SENT
    - ResourceMetrics.MEAN_OVERALL_CPU_UTILIZATION (%)
"""
