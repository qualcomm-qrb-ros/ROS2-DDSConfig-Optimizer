# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Environment module: collects and validates system environment information.

Collects:
- OS version
- ROS 2 distribution (from ROS_DISTRO environment variable)
- Active ROS 2 nodes (via 'ros2 node list')
- Active ROS 2 topics with types (via 'ros2 topic list -t')
- CPU info (conditional: only if cpu_usage requirement is present)
- Memory info (conditional: only if memory_usage requirement is present)
"""
