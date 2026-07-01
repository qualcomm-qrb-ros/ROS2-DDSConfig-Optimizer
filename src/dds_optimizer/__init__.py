# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
ROS2 DDSConfig Optimizer

An AI-driven tool that automatically optimizes FastDDS (eProsima Fast DDS) configuration
parameters for ROS2 applications to meet user-defined performance requirements.

The optimizer uses a Large Language Model (LLM) to intelligently tune ~30 performance-critical
DDS parameters, then validates the configuration by running ros2_benchmark tests in an
iterative feedback loop.
"""

__version__ = "0.1.0"
__author__ = "ROS2 DDSConfig Optimizer"
