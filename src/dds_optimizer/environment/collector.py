# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Environment Collector: gathers system and ROS2 environment information.

Collection strategy:
- Minimum set (always collected): OS version, ROS2 distro, active nodes/topics
- Conditional (based on user requirements):
    - CPU info: collected only if cpu_usage requirement is present
    - Memory info: collected only if memory_usage requirement is present

ROS2 commands used:
    ros2 node list                  → list active nodes
    ros2 topic list -t              → list topics with message types
    ros2 topic info <topic>         → get publisher/subscriber counts
"""

import os
import platform
import subprocess
from typing import List, Optional

import psutil

from ..models import (
    CpuInfo,
    EnvironmentInfo,
    MemoryInfo,
    PerformanceRequirements,
    PipelineTopology,
    TopicConnection,
    TopicInfo,
)
from ..utils.logger import get_logger

logger = get_logger(__name__)


def _run_command(cmd: List[str], timeout: int = 10) -> Optional[str]:
    """
    Run a shell command and return its stdout output.

    Inherits the current process environment (including ROS_DOMAIN_ID,
    ROS_DISTRO, LD_LIBRARY_PATH, etc.) so that ROS2 CLI commands work
    correctly when a specific domain ID is set.

    Args:
        cmd: Command and arguments as a list (e.g., ['ros2', 'node', 'list']).
        timeout: Maximum seconds to wait for the command to complete.

    Returns:
        stdout output as a string, or None if the command failed/timed out.
    """
    try:
        # Pass the full current environment so ROS_DOMAIN_ID and other
        # ROS2 environment variables are inherited by the subprocess.
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _collect_os_version() -> str:
    """
    Collect the operating system version string.

    Reads /etc/os-release for a human-readable description.
    Falls back to platform.platform() if the file is not available.

    Returns:
        OS version string (e.g., "Ubuntu 24.04.1 LTS").
    """
    # Try reading /etc/os-release for a clean description
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    # Remove PRETTY_NAME=" and trailing "
                    return line.split("=", 1)[1].strip().strip('"')
    except (FileNotFoundError, PermissionError):
        pass

    # Fallback to platform module
    return platform.platform()


def _collect_ros2_distro() -> str:
    """
    Collect the active ROS 2 distribution name.

    Reads the ROS_DISTRO environment variable, which is set when a ROS 2
    workspace is sourced (e.g., 'source /opt/ros/<distro>/setup.bash').

    Returns:
        ROS 2 distribution name (e.g., "jazzy", "humble"), or "unknown" if not set.
    """
    return os.environ.get("ROS_DISTRO", "unknown")


def _collect_active_nodes() -> List[str]:
    """
    Collect the list of currently active ROS2 nodes.

    Runs 'ros2 node list' and parses the output.

    Returns:
        List of node names (e.g., ['/camera_node', '/lidar_node']).
        Returns empty list if ROS2 is not available or no nodes are running.
    """
    output = _run_command(["ros2", "node", "list"])
    if not output:
        return []

    # Each line is a node name
    nodes = [line.strip() for line in output.splitlines() if line.strip()]
    return nodes


def _collect_active_topics() -> List[TopicInfo]:
    """
    Collect the list of active ROS2 topics with their message types.

    Runs 'ros2 topic list -t' which outputs lines like:
        /camera/image_raw [sensor_msgs/msg/Image]
        /cmd_vel [geometry_msgs/msg/Twist]

    For each topic, also queries publisher/subscriber counts via
    'ros2 topic info <topic>'.

    Returns:
        List of TopicInfo objects with name, msg_type, and counts.
        Returns empty list if ROS2 is not available or no topics exist.
    """
    output = _run_command(["ros2", "topic", "list", "-t"])
    if not output:
        return []

    topics: List[TopicInfo] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # Parse "topic_name [msg_type]" format
        if "[" in line and "]" in line:
            parts = line.split("[", 1)
            topic_name = parts[0].strip()
            msg_type = parts[1].rstrip("]").strip()
        else:
            # Fallback: just the topic name without type
            topic_name = line
            msg_type = "unknown"

        # Get publisher/subscriber counts (best effort, skip if slow)
        pub_count = 0
        sub_count = 0
        info_output = _run_command(["ros2", "topic", "info", topic_name], timeout=5)
        if info_output:
            for info_line in info_output.splitlines():
                info_line = info_line.strip()
                if info_line.startswith("Publisher count:"):
                    try:
                        pub_count = int(info_line.split(":", 1)[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif info_line.startswith("Subscription count:"):
                    try:
                        sub_count = int(info_line.split(":", 1)[1].strip())
                    except (ValueError, IndexError):
                        pass

        topics.append(TopicInfo(
            name=topic_name,
            msg_type=msg_type,
            publisher_count=pub_count,
            subscriber_count=sub_count,
        ))

    return topics


def _collect_cpu_info() -> CpuInfo:
    """
    Collect CPU hardware information using psutil.

    Returns:
        CpuInfo with core counts, model name, and current frequency.
    """
    # Get CPU model from /proc/cpuinfo (Linux)
    cpu_model = "Unknown CPU"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except (FileNotFoundError, PermissionError):
        cpu_model = platform.processor() or "Unknown CPU"

    # Get frequency
    freq = psutil.cpu_freq()
    frequency_mhz = freq.current if freq else None

    return CpuInfo(
        cores_physical=psutil.cpu_count(logical=False) or 1,
        cores_logical=psutil.cpu_count(logical=True) or 1,
        model=cpu_model,
        frequency_mhz=frequency_mhz,
    )


def _collect_memory_info() -> MemoryInfo:
    """
    Collect system memory information using psutil.

    Returns:
        MemoryInfo with total, available RAM in MB and usage percentage.
    """
    mem = psutil.virtual_memory()
    return MemoryInfo(
        total_mb=mem.total / (1024 * 1024),
        available_mb=mem.available / (1024 * 1024),
        used_percent=mem.percent,
    )


def collect_environment(
    requirements: Optional[PerformanceRequirements] = None,
) -> EnvironmentInfo:
    """
    Collect all required environment information.

    This is the main entry point for environment collection. It always
    collects the minimum required set (OS, ROS2, nodes, topics), and
    conditionally collects CPU/memory info based on the requirements.

    Args:
        requirements: Performance requirements to determine what additional
                      info to collect. If None, only minimum info is collected.

    Returns:
        EnvironmentInfo with all collected system information.

    Example:
        >>> from dds_optimizer.models import PerformanceRequirements, CpuUsageRequirement
        >>> reqs = PerformanceRequirements(cpu_usage=CpuUsageRequirement(max_percent=50))
        >>> env = collect_environment(reqs)
        >>> print(env.os_version)
        'Ubuntu 22.04.3 LTS'
        >>> print(env.cpu_info.cores_logical)
        16
    """
    # Always collect minimum required info
    os_version = _collect_os_version()
    ros2_distro = _collect_ros2_distro()
    active_nodes = _collect_active_nodes()
    active_topics = _collect_active_topics()

    # Conditionally collect CPU info
    cpu_info = None
    if requirements is not None and requirements.cpu_usage is not None:
        cpu_info = _collect_cpu_info()

    # Conditionally collect memory info
    memory_info = None
    if requirements is not None and requirements.memory_usage is not None:
        memory_info = _collect_memory_info()

    return EnvironmentInfo(
        os_version=os_version,
        ros2_distro=ros2_distro,
        active_nodes=active_nodes,
        active_topics=active_topics,
        cpu_info=cpu_info,
        memory_info=memory_info,
    )


# ROS2 system topics that are always present and not part of any user pipeline.
# Filtered out from pipeline topology to avoid sending noise to the LLM.
_SYSTEM_TOPICS: frozenset = frozenset({
    "/parameter_events",
    "/rosout",
})


def collect_pipeline_topology() -> PipelineTopology:
    """
    Collect the running ROS2 pipeline topology.

    Tries the rclpy API path first (ros2_api.py), which provides richer data
    (full node paths with namespaces, QoS, message sizes, process groups) with
    no subprocess overhead. Falls back to CLI-based collection if rclpy is
    unavailable or the API call fails.

    Called from a background thread while the benchmark is running.

    Returns:
        PipelineTopology with nodes, topic connections, and process groups.
        Returns an empty topology if neither approach succeeds.
    """
    from .ros2_api import collect_pipeline_topology_via_api

    try:
        return collect_pipeline_topology_via_api()
    except Exception as e:
        logger.warning(
            f"rclpy API topology collection failed ({e}); falling back to CLI"
        )
        return _collect_pipeline_topology_via_cli()


def _collect_pipeline_topology_via_cli() -> PipelineTopology:
    """
    CLI-based fallback for collect_pipeline_topology().

    Used when rclpy is not available (e.g., ROS2 workspace not sourced in the
    Python environment). Calls 'ros2 topic list' and 'ros2 topic info -v'.

    Note: CLI-based collection has lower fidelity — node names may lack their
    full namespace path, and QoS / message size are not available.
    """
    nodes = _collect_active_nodes()

    topic_output = _run_command(["ros2", "topic", "list", "-t"])
    if not topic_output:
        return PipelineTopology(nodes=nodes, topics=[])

    topic_connections: List[TopicConnection] = []

    for line in topic_output.splitlines():
        line = line.strip()
        if not line:
            continue

        if "[" in line and "]" in line:
            parts = line.split("[", 1)
            topic_name = parts[0].strip()
            msg_type = parts[1].rstrip("]").strip()
        else:
            topic_name = line
            msg_type = "unknown"

        if topic_name in _SYSTEM_TOPICS:
            continue

        publishers: List[str] = []
        subscribers: List[str] = []

        verbose_output = _run_command(
            ["ros2", "topic", "info", "-v", topic_name], timeout=5
        )
        if verbose_output:
            current_section = None
            for info_line in verbose_output.splitlines():
                info_line_stripped = info_line.strip()
                if info_line_stripped.startswith("Publisher count:"):
                    current_section = "publishers"
                elif info_line_stripped.startswith("Subscription count:"):
                    current_section = "subscribers"
                elif info_line_stripped.startswith("Node name:"):
                    node_name = info_line_stripped.split(":", 1)[1].strip()
                    if current_section == "publishers":
                        publishers.append(node_name)
                    elif current_section == "subscribers":
                        subscribers.append(node_name)

        topic_connections.append(TopicConnection(
            name=topic_name,
            msg_type=msg_type,
            publishers=publishers,
            subscribers=subscribers,
        ))

    return PipelineTopology(nodes=nodes, topics=topic_connections)
