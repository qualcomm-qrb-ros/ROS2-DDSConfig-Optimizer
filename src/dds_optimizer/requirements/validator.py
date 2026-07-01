# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Requirements Validator: validates parsed requirements for completeness and consistency.

Checks performed:
1. Benchmark test file exists and is a Python file
2. At least one performance requirement is specified
3. LLM API key environment variable is set
4. Numeric values are within reasonable ranges
5. Required (non-optional) requirements have target values specified
"""

import os
from pathlib import Path
from typing import List

from ..models import RequirementsConfig


class RequirementsValidationError(Exception):
    """Raised when requirements validation fails."""
    pass


def validate_requirements(config: RequirementsConfig) -> List[str]:
    """
    Validate a parsed RequirementsConfig for completeness and consistency.

    This function performs a comprehensive set of checks and collects all
    validation errors before raising, so the user sees all issues at once.

    Args:
        config: The parsed requirements configuration to validate.

    Returns:
        List of warning messages (non-fatal issues). Empty list means no warnings.

    Raises:
        RequirementsValidationError: If any critical validation check fails.
                                     The error message lists all failures found.

    Example:
        >>> config = parse_requirements("user_requirements.xml")
        >>> warnings = validate_requirements(config)
        >>> for w in warnings:
        ...     print(f"WARNING: {w}")
    """
    errors: List[str] = []
    warnings: List[str] = []

    # ------------------------------------------------------------------
    # 1. Validate benchmark configuration
    # ------------------------------------------------------------------
    _validate_benchmark(config, errors, warnings)

    # ------------------------------------------------------------------
    # 2. Validate performance requirements
    # ------------------------------------------------------------------
    _validate_performance_requirements(config, errors, warnings)

    # ------------------------------------------------------------------
    # 3. Validate LLM configuration
    # ------------------------------------------------------------------
    _validate_llm_config(config, errors, warnings)

    # ------------------------------------------------------------------
    # 4. Validate optimization settings
    # ------------------------------------------------------------------
    _validate_optimization_settings(config, errors, warnings)

    # Raise if any errors were found
    if errors:
        error_msg = "Requirements validation failed with the following errors:\n"
        error_msg += "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
        raise RequirementsValidationError(error_msg)

    return warnings


def _validate_benchmark(
    config: RequirementsConfig,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate the benchmark configuration section."""
    benchmark = config.benchmark

    # Check test file exists
    test_file_path = Path(benchmark.test_file)
    if not test_file_path.exists():
        errors.append(
            f"Benchmark test file does not exist: '{benchmark.test_file}'"
        )
    elif not test_file_path.is_file():
        errors.append(
            f"Benchmark test file path is not a file: '{benchmark.test_file}'"
        )
    elif test_file_path.suffix.lower() != ".py":
        warnings.append(
            f"Benchmark test file does not have .py extension: '{benchmark.test_file}'"
        )

    # Check launch command is not empty
    if not benchmark.launch_command.strip():
        errors.append("Benchmark launch_command cannot be empty")


def _validate_performance_requirements(
    config: RequirementsConfig,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate the performance requirements section."""
    perf = config.performance_requirements

    # Check at least one requirement is specified
    has_any_requirement = any([
        perf.latency is not None,
        perf.throughput is not None,
        perf.reliability is not None,
        perf.cpu_usage is not None,
        perf.memory_usage is not None,
    ])
    if not has_any_requirement:
        warnings.append(
            "No performance requirements specified. "
            "The optimizer will generate a config but cannot evaluate it."
        )

    # Validate latency requirements
    if perf.latency is not None:
        lat = perf.latency
        if not lat.optional:
            # Required latency must have at least one target
            if lat.target_mean_ms is None and lat.target_p95_ms is None and lat.target_p99_ms is None:
                errors.append(
                    "Latency requirement is marked as required (optional=false) "
                    "but no target values are specified"
                )
        # Validate ordering: mean <= p95 <= p99
        if lat.target_mean_ms and lat.target_p95_ms:
            if lat.target_mean_ms > lat.target_p95_ms:
                errors.append(
                    f"Latency target_mean_ms ({lat.target_mean_ms}) must be <= "
                    f"target_p95_ms ({lat.target_p95_ms})"
                )
        if lat.target_p95_ms and lat.target_p99_ms:
            if lat.target_p95_ms > lat.target_p99_ms:
                errors.append(
                    f"Latency target_p95_ms ({lat.target_p95_ms}) must be <= "
                    f"target_p99_ms ({lat.target_p99_ms})"
                )
        # Validate positive values
        for name, val in [
            ("target_mean_ms", lat.target_mean_ms),
            ("target_p95_ms", lat.target_p95_ms),
            ("target_p99_ms", lat.target_p99_ms),
        ]:
            if val is not None and val <= 0:
                errors.append(f"Latency {name} must be positive, got {val}")

    # Validate throughput requirements
    if perf.throughput is not None:
        thr = perf.throughput
        if thr.target_msgs_per_sec is not None and thr.target_msgs_per_sec <= 0:
            errors.append(
                f"Throughput target_msgs_per_sec must be positive, got {thr.target_msgs_per_sec}"
            )
        if thr.target_mbps is not None and thr.target_mbps <= 0:
            errors.append(
                f"Throughput target_mbps must be positive, got {thr.target_mbps}"
            )

    # Validate reliability requirements
    if perf.reliability is not None:
        rel = perf.reliability
        if rel.max_packet_loss_rate is not None:
            if not (0.0 <= rel.max_packet_loss_rate <= 1.0):
                errors.append(
                    f"Reliability max_packet_loss_rate must be between 0.0 and 1.0, "
                    f"got {rel.max_packet_loss_rate}"
                )

    # Validate CPU usage requirements
    if perf.cpu_usage is not None:
        cpu = perf.cpu_usage
        if cpu.max_percent is not None:
            if not (0.0 < cpu.max_percent <= 100.0):
                errors.append(
                    f"CPU max_percent must be between 0 and 100, got {cpu.max_percent}"
                )

    # Validate memory usage requirements
    if perf.memory_usage is not None:
        mem = perf.memory_usage
        if mem.max_mb is not None and mem.max_mb <= 0:
            errors.append(
                f"Memory max_mb must be positive, got {mem.max_mb}"
            )


def _validate_llm_config(
    config: RequirementsConfig,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate the LLM configuration section."""
    llm = config.llm_config

    # Check API key environment variable is set
    api_key = os.environ.get(llm.api_key_env)
    if not api_key:
        errors.append(
            f"LLM API key environment variable '{llm.api_key_env}' is not set. "
            f"Please set it with: export {llm.api_key_env}=<your-api-key>"
        )
    elif len(api_key) < 10:
        warnings.append(
            f"LLM API key in '{llm.api_key_env}' seems very short ({len(api_key)} chars). "
            "Please verify it is correct."
        )

    # Check base_url is not empty (only validate if explicitly set; None means use provider default)
    if llm.base_url is not None and not llm.base_url.strip():
        errors.append("LLM base_url cannot be empty")

    # Check model is not empty
    if not llm.model.strip():
        errors.append("LLM model cannot be empty")


def _validate_optimization_settings(
    config: RequirementsConfig,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate the optimization settings section."""
    settings = config.optimization_settings

    if settings.max_iterations < 1:
        errors.append(
            f"max_iterations must be at least 1, got {settings.max_iterations}"
        )
    if settings.max_iterations > 20:
        warnings.append(
            f"max_iterations is set to {settings.max_iterations}, which may take a long time. "
            "Consider using 5-10 iterations for most use cases."
        )

    if not (0.0 <= settings.convergence_threshold <= 1.0):
        errors.append(
            f"convergence_threshold must be between 0.0 and 1.0, "
            f"got {settings.convergence_threshold}"
        )
