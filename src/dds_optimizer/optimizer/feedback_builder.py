# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Feedback Builder: constructs performance gap descriptions for LLM feedback prompts.

Converts EvaluationResult into human-readable gap descriptions that the LLM
can use to understand what needs to improve and by how much.

Example output:
    {
        "latency_mean_ms": "[FAILED-REQUIRED] Actual: 18.5ms, Target: ≤10ms, Gap: +85% over target",
        "throughput_msgs_per_sec": "[PASSED-optional] Actual: 1200 msgs/sec, Target: ≥1000 msgs/sec",
        "packet_loss_rate": "[FAILED-REQUIRED] Actual: 0.5%, Target: ≤0.1%, Gap: 5x over target",
    }
"""

from typing import Dict

from ..models import BenchmarkResults, PerformanceRequirements
from .evaluator import EvaluationResult
from ..utils.logger import get_logger

logger = get_logger(__name__)


def build_performance_gaps(
    eval_result: EvaluationResult,
    results: BenchmarkResults,
    requirements: PerformanceRequirements,
) -> Dict[str, str]:
    """
    Build a dictionary of performance gap descriptions for LLM feedback.

    For each evaluated metric, creates a human-readable description of:
    - Whether the metric passed or failed
    - Whether it's required or optional
    - The actual measured value
    - The target value
    - The gap (how far from target, as percentage or ratio)

    Args:
        eval_result: Evaluation result from the evaluator.
        results: Benchmark results from the latest test run.
        requirements: Performance requirements for context.

    Returns:
        Dictionary mapping metric names to gap description strings.
        Failed required metrics are marked with [FAILED-REQUIRED].
        Failed optional metrics are marked with [FAILED-optional].
        Passed metrics are marked with [PASSED].

    Example:
        >>> gaps = build_performance_gaps(eval_result, results, requirements)
        >>> for metric, desc in gaps.items():
        ...     print(f"{metric}: {desc}")
    """
    gaps: Dict[str, str] = {}

    for metric_name, status in eval_result.metric_status.items():
        met = status["met"]
        actual = status["actual"]
        target = status["target"]
        operator = status["operator"]
        is_optional = status["optional"]

        # Determine status label
        if met:
            status_label = "[PASSED]"
        elif is_optional:
            status_label = "[FAILED-optional]"
        else:
            status_label = "[FAILED-REQUIRED]"

        # Format actual and target values with appropriate units
        actual_str, target_str = _format_metric_values(metric_name, actual, target)

        # Compute gap description
        gap_str = _compute_gap_description(metric_name, actual, target, operator, met)

        gaps[metric_name] = (
            f"{status_label} Actual: {actual_str}, Target: {operator}{target_str}"
            + (f", Gap: {gap_str}" if not met else "")
        )

    # Add metrics that couldn't be evaluated (missing from results)
    _add_missing_metrics(gaps, results, requirements)

    return gaps


def _format_metric_values(metric_name: str, actual: float, target: float):
    """Format metric values with appropriate units for readability."""
    if "latency" in metric_name or "jitter" in metric_name:
        return f"{actual:.2f}ms", f"{target:.2f}ms"
    elif "packet_loss" in metric_name:
        return f"{actual * 100:.4f}%", f"{target * 100:.4f}%"
    elif "cpu" in metric_name:
        return f"{actual:.1f}%", f"{target:.1f}%"
    elif "msgs_per_sec" in metric_name:
        return f"{actual:.1f} msgs/sec", f"{target:.1f} msgs/sec"
    elif "mbps" in metric_name:
        return f"{actual:.1f} Mbps", f"{target:.1f} Mbps"
    else:
        return f"{actual:.4g}", f"{target:.4g}"


def _compute_gap_description(
    metric_name: str,
    actual: float,
    target: float,
    operator: str,
    met: bool,
) -> str:
    """Compute a human-readable gap description."""
    if met:
        return "within target"

    if operator == "≤":
        # Lower is better: actual > target
        if target > 0:
            overshoot_pct = ((actual - target) / target) * 100
            ratio = actual / target
            return f"+{overshoot_pct:.1f}% over target ({ratio:.1f}x)"
        else:
            return f"actual={actual:.4g} exceeds target={target:.4g}"
    elif operator == "≥":
        # Higher is better: actual < target
        if target > 0:
            shortfall_pct = ((target - actual) / target) * 100
            return f"-{shortfall_pct:.1f}% below target"
        else:
            return f"actual={actual:.4g} below target={target:.4g}"
    else:
        return f"actual={actual:.4g}, target={target:.4g}"


def _add_missing_metrics(
    gaps: Dict[str, str],
    results: BenchmarkResults,
    requirements: PerformanceRequirements,
) -> None:
    """
    Add entries for metrics that were required but couldn't be measured.

    This happens when the benchmark doesn't produce certain metrics
    (e.g., MEAN_LATENCY requires message_key_match=True).
    """
    # Check latency
    if requirements.latency is not None:
        if requirements.latency.target_mean_ms is not None and results.mean_latency_ms is None:
            gaps["latency_mean_ms"] = (
                "[MISSING] Mean latency not available in benchmark results. "
                "Consider enabling message_key_match=True in your benchmark config."
            )

    # Check throughput
    if requirements.throughput is not None:
        if requirements.throughput.target_msgs_per_sec is not None and results.msgs_per_sec is None:
            gaps["throughput_msgs_per_sec"] = (
                "[MISSING] Throughput not available in benchmark results."
            )

    # Check reliability
    if requirements.reliability is not None:
        if requirements.reliability.max_packet_loss_rate is not None and results.packet_loss_rate is None:
            gaps["packet_loss_rate"] = (
                "[MISSING] Packet loss rate not available in benchmark results."
            )

    # Check CPU
    if requirements.cpu_usage is not None:
        if requirements.cpu_usage.max_percent is not None and results.cpu_percent is None:
            gaps["cpu_percent"] = (
                "[MISSING] CPU utilization not available in benchmark results."
            )
