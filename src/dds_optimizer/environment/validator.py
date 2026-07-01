# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Environment Validator: validates collected environment against requirements.

Checks performed:
1. ROS 2 is properly sourced (ROS_DISTRO environment variable is set)
2. Benchmark test file exists (cross-check with requirements)
3. Warns if no active ROS 2 nodes/topics are found
"""

from typing import List

from ..models import EnvironmentInfo, RequirementsConfig


class EnvironmentValidationError(Exception):
    """Raised when environment validation fails with critical errors."""
    pass


def validate_environment(
    env: EnvironmentInfo,
    requirements: RequirementsConfig,
) -> List[str]:
    """
    Validate the collected environment against system requirements.

    Args:
        env: Collected environment information.
        requirements: User requirements configuration (for cross-checks).

    Returns:
        List of warning messages (non-fatal). Empty list means no warnings.

    Raises:
        EnvironmentValidationError: If critical environment checks fail.
                                    The error message lists all failures.

    Example:
        >>> env = collect_environment()
        >>> warnings = validate_environment(env, requirements)
        >>> for w in warnings:
        ...     print(f"WARNING: {w}")
    """
    errors: List[str] = []
    warnings: List[str] = []

    # ------------------------------------------------------------------
    # 1. Validate ROS 2 distribution is sourced
    # ------------------------------------------------------------------
    _validate_ros2_distro(env, errors, warnings)

    # ------------------------------------------------------------------
    # 2. Validate ROS 2 nodes and topics
    # ------------------------------------------------------------------
    # Skip this check in benchmark mode: nodes are started by the benchmark
    # script itself, so they won't be running at validation time.
    has_benchmark = bool(requirements.benchmark.test_file)
    if not has_benchmark:
        _validate_ros2_activity(env, warnings)

    # ------------------------------------------------------------------
    # 3. Cross-check benchmark file existence
    # ------------------------------------------------------------------
    _validate_benchmark_file(requirements, errors)

    # Raise if any critical errors were found
    if errors:
        error_msg = "Environment validation failed with the following errors:\n"
        error_msg += "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
        raise EnvironmentValidationError(error_msg)

    return warnings


def _validate_ros2_distro(
    env: EnvironmentInfo,
    errors: List[str],
    warnings: List[str],
) -> None:
    """
    Validate that a ROS 2 workspace is sourced.

    Checks that the ROS_DISTRO environment variable is set, which indicates
    that a ROS 2 workspace has been sourced. Any ROS 2 distribution that
    uses FastDDS as its default middleware is supported.
    """
    distro = env.ros2_distro.lower()

    if distro == "unknown":
        errors.append(
            "ROS 2 distribution is not set (ROS_DISTRO environment variable is missing). "
            "Please source your ROS 2 workspace: source /opt/ros/<distro>/setup.bash"
        )


def _validate_ros2_activity(
    env: EnvironmentInfo,
    warnings: List[str],
) -> None:
    """
    Warn if no active ROS 2 nodes or topics are found.

    While the optimizer can still generate a config without active nodes,
    the LLM prompt will be less informative without this context.
    """
    if not env.active_nodes:
        warnings.append(
            "No active ROS 2 nodes found. "
            "The LLM will generate a generic configuration without node-specific context. "
            "Consider starting your ROS 2 application before running the optimizer."
        )

    if not env.active_topics:
        warnings.append(
            "No active ROS 2 topics found. "
            "The LLM will generate a generic configuration without topic-specific context."
        )


def _validate_benchmark_file(
    requirements: RequirementsConfig,
    errors: List[str],
) -> None:
    """
    Validate that the benchmark test file specified in requirements exists.

    This is a cross-check between the requirements and the filesystem.
    The requirements validator also checks this, but we re-verify here
    as the environment validation is the last gate before optimization starts.
    """
    import os
    test_file = requirements.benchmark.test_file
    if not os.path.isfile(test_file):
        errors.append(
            f"Benchmark test file not found: '{test_file}'. "
            "Please verify the path in your user_requirements.xml."
        )
