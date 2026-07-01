# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Evaluator: compares benchmark results against user requirements.

Determines:
1. Which required (non-optional) metrics are met/failed
2. Which optional metrics are met/failed
3. A composite performance score (0.0 to 1.0, higher = better)
4. Whether convergence has been achieved

The performance score is used to:
- Track improvement across iterations
- Determine the best iteration to save as final config
- Detect convergence (< threshold improvement between iterations)
"""

from typing import Dict, Optional, Tuple

from ..models import BenchmarkResults, PerformanceRequirements
from ..utils.logger import get_logger

logger = get_logger(__name__)


class EvaluationResult:
    """
    Result of evaluating benchmark results against requirements.

    Attributes:
        required_metrics_met: True if ALL non-optional requirements are satisfied.
        optional_metrics_met: True if ALL optional requirements are satisfied.
        all_metrics_met: True if both required and optional are satisfied.
        performance_score: Composite score 0.0-1.0 (higher = better).
        metric_status: Dict of metric_name → (met: bool, actual: float, target: float).
        failed_required: List of required metric names that failed.
        failed_optional: List of optional metric names that failed.
    """

    def __init__(self) -> None:
        self.required_metrics_met: bool = True
        self.optional_metrics_met: bool = True
        self.all_metrics_met: bool = True
        self.performance_score: float = 0.0
        self.metric_status: Dict[str, dict] = {}
        self.failed_required: list = []
        self.failed_optional: list = []


def evaluate_results(
    results: BenchmarkResults,
    requirements: PerformanceRequirements,
) -> EvaluationResult:
    """
    Evaluate benchmark results against performance requirements.

    For each requirement:
    - Checks if the measured value meets the target
    - Records whether it's a required or optional metric
    - Computes a per-metric score (0.0 = far from target, 1.0 = meets target)

    The composite score is the weighted average of all metric scores,
    with required metrics weighted 2x more than optional metrics.

    Args:
        results: Benchmark results from the latest test run.
        requirements: Performance requirements to evaluate against.

    Returns:
        EvaluationResult with detailed pass/fail status and scores.

    Example:
        >>> eval_result = evaluate_results(results, requirements)
        >>> if eval_result.required_metrics_met:
        ...     print("All required metrics met!")
        >>> else:
        ...     print(f"Failed: {eval_result.failed_required}")
    """
    eval_result = EvaluationResult()
    scores = []
    weights = []

    # -----------------------------------------------------------------------
    # Evaluate latency requirements
    # -----------------------------------------------------------------------
    if requirements.latency is not None:
        lat_req = requirements.latency
        weight = 1.0 if lat_req.optional else 2.0

        if lat_req.target_mean_ms is not None and results.mean_latency_ms is not None:
            met, score = _evaluate_upper_bound(
                actual=results.mean_latency_ms,
                target=lat_req.target_mean_ms,
                metric_name="latency_mean_ms",
            )
            _record_metric(eval_result, "latency_mean_ms", met, lat_req.optional,
                           results.mean_latency_ms, lat_req.target_mean_ms, "≤")
            scores.append(score)
            weights.append(weight)

        if lat_req.target_p95_ms is not None and results.p95_latency_ms is not None:
            met, score = _evaluate_upper_bound(
                actual=results.p95_latency_ms,
                target=lat_req.target_p95_ms,
                metric_name="latency_p95_ms",
            )
            _record_metric(eval_result, "latency_p95_ms", met, lat_req.optional,
                           results.p95_latency_ms, lat_req.target_p95_ms, "≤")
            scores.append(score)
            weights.append(weight)

        if lat_req.target_p99_ms is not None and results.p99_latency_ms is not None:
            met, score = _evaluate_upper_bound(
                actual=results.p99_latency_ms,
                target=lat_req.target_p99_ms,
                metric_name="latency_p99_ms",
            )
            _record_metric(eval_result, "latency_p99_ms", met, lat_req.optional,
                           results.p99_latency_ms, lat_req.target_p99_ms, "≤")
            scores.append(score)
            weights.append(weight)

    # -----------------------------------------------------------------------
    # Evaluate throughput requirements
    # -----------------------------------------------------------------------
    if requirements.throughput is not None:
        thr_req = requirements.throughput
        weight = 1.0 if thr_req.optional else 2.0

        if thr_req.target_msgs_per_sec is not None and results.msgs_per_sec is not None:
            met, score = _evaluate_lower_bound(
                actual=results.msgs_per_sec,
                target=thr_req.target_msgs_per_sec,
                metric_name="throughput_msgs_per_sec",
            )
            _record_metric(eval_result, "throughput_msgs_per_sec", met, thr_req.optional,
                           results.msgs_per_sec, thr_req.target_msgs_per_sec, "≥")
            scores.append(score)
            weights.append(weight)

    # -----------------------------------------------------------------------
    # Evaluate reliability requirements
    # -----------------------------------------------------------------------
    if requirements.reliability is not None:
        rel_req = requirements.reliability
        weight = 1.0 if rel_req.optional else 2.0

        if rel_req.max_packet_loss_rate is not None and results.packet_loss_rate is not None:
            met, score = _evaluate_upper_bound(
                actual=results.packet_loss_rate,
                target=rel_req.max_packet_loss_rate,
                metric_name="packet_loss_rate",
            )
            _record_metric(eval_result, "packet_loss_rate", met, rel_req.optional,
                           results.packet_loss_rate, rel_req.max_packet_loss_rate, "≤")
            scores.append(score)
            weights.append(weight)

    # -----------------------------------------------------------------------
    # Evaluate CPU usage requirements
    # -----------------------------------------------------------------------
    if requirements.cpu_usage is not None:
        cpu_req = requirements.cpu_usage
        weight = 1.0 if cpu_req.optional else 2.0

        if cpu_req.max_percent is not None and results.cpu_percent is not None:
            met, score = _evaluate_upper_bound(
                actual=results.cpu_percent,
                target=cpu_req.max_percent,
                metric_name="cpu_percent",
            )
            _record_metric(eval_result, "cpu_percent", met, cpu_req.optional,
                           results.cpu_percent, cpu_req.max_percent, "≤")
            scores.append(score)
            weights.append(weight)

    # -----------------------------------------------------------------------
    # Evaluate memory usage requirements
    # -----------------------------------------------------------------------
    if requirements.memory_usage is not None:
        mem_req = requirements.memory_usage
        weight = 1.0 if mem_req.optional else 2.0

        if mem_req.max_mb is not None and results.memory_mb is not None:
            met, score = _evaluate_upper_bound(
                actual=results.memory_mb,
                target=mem_req.max_mb,
                metric_name="memory_mb",
            )
            _record_metric(eval_result, "memory_mb", met, mem_req.optional,
                           results.memory_mb, mem_req.max_mb, "≤")
            scores.append(score)
            weights.append(weight)

    # -----------------------------------------------------------------------
    # Compute composite performance score
    # -----------------------------------------------------------------------
    if scores:
        total_weight = sum(weights)
        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        eval_result.performance_score = weighted_sum / total_weight
    else:
        # No metrics could be evaluated (results missing)
        eval_result.performance_score = 0.0
        logger.warning(
            "No metrics could be evaluated (benchmark results may be missing). "
            "Performance score set to 0.0."
        )
        # If there are any required metrics defined but none could be measured,
        # treat all required metrics as failed — a missing benchmark result
        # cannot be considered a pass.
        _has_required = any([
            requirements.latency is not None and not requirements.latency.optional,
            requirements.throughput is not None and not requirements.throughput.optional,
            requirements.reliability is not None and not requirements.reliability.optional,
            requirements.cpu_usage is not None and not requirements.cpu_usage.optional,
            requirements.memory_usage is not None and not requirements.memory_usage.optional,
        ])
        if _has_required:
            eval_result.required_metrics_met = False

    # -----------------------------------------------------------------------
    # Determine overall pass/fail
    # -----------------------------------------------------------------------
    eval_result.all_metrics_met = (
        eval_result.required_metrics_met and eval_result.optional_metrics_met
    )

    # Log evaluation summary
    _log_evaluation_summary(eval_result)

    return eval_result


def _evaluate_upper_bound(
    actual: float,
    target: float,
    metric_name: str,
) -> Tuple[bool, float]:
    """
    Evaluate a metric where lower is better (e.g., latency, packet loss).

    Score = 1.0 if actual <= target (requirement met)
    Score = target / actual if actual > target (proportional to how far over)

    Args:
        actual: Measured value.
        target: Maximum acceptable value.
        metric_name: Name for logging.

    Returns:
        Tuple of (met: bool, score: float).
    """
    met = actual <= target
    if met:
        score = 1.0
    else:
        # Score decreases as actual exceeds target
        # e.g., actual=20ms, target=10ms → score = 10/20 = 0.5
        score = target / actual if actual > 0 else 0.0
    return met, score


def _evaluate_lower_bound(
    actual: float,
    target: float,
    metric_name: str,
) -> Tuple[bool, float]:
    """
    Evaluate a metric where higher is better (e.g., throughput).

    Score = 1.0 if actual >= target (requirement met)
    Score = actual / target if actual < target (proportional to how far under)

    Args:
        actual: Measured value.
        target: Minimum acceptable value.
        metric_name: Name for logging.

    Returns:
        Tuple of (met: bool, score: float).
    """
    met = actual >= target
    if met:
        score = 1.0
    else:
        # Score decreases as actual falls below target
        score = actual / target if target > 0 else 0.0
    return met, score


def _record_metric(
    eval_result: EvaluationResult,
    metric_name: str,
    met: bool,
    is_optional: bool,
    actual: float,
    target: float,
    operator: str,
) -> None:
    """Record a metric evaluation result and update pass/fail tracking."""
    eval_result.metric_status[metric_name] = {
        "met": met,
        "actual": actual,
        "target": target,
        "operator": operator,
        "optional": is_optional,
    }

    if not met:
        if is_optional:
            eval_result.optional_metrics_met = False
            eval_result.failed_optional.append(metric_name)
        else:
            eval_result.required_metrics_met = False
            eval_result.failed_required.append(metric_name)


def _log_evaluation_summary(eval_result: EvaluationResult) -> None:
    """Log a summary of the evaluation results."""
    lines = [
        f"Evaluation summary (score: {eval_result.performance_score:.3f}):"
    ]

    for metric_name, status in eval_result.metric_status.items():
        icon = "✓" if status["met"] else "✗"
        req_str = "optional" if status["optional"] else "REQUIRED"
        lines.append(
            f"  {icon} [{req_str}] {metric_name}: "
            f"{status['actual']:.4g} {status['operator']} {status['target']:.4g}"
        )

    if eval_result.required_metrics_met:
        lines.append("  → All REQUIRED metrics met!")
    else:
        lines.append(f"  → REQUIRED metrics FAILED: {eval_result.failed_required}")

    logger.info("\n".join(lines))


def check_convergence(
    current_score: float,
    previous_score: float,
    threshold: float,
) -> bool:
    """
    Check if the optimization has converged.

    Convergence is detected when the improvement between iterations is
    less than the threshold fraction.

    Args:
        current_score: Performance score from the current iteration.
        previous_score: Performance score from the previous iteration.
        threshold: Minimum improvement fraction to continue (e.g., 0.05 = 5%).

    Returns:
        True if converged (improvement < threshold), False otherwise.

    Example:
        >>> converged = check_convergence(0.95, 0.93, threshold=0.05)
        >>> # improvement = (0.95 - 0.93) / 0.93 = 2.15% < 5% → converged
        >>> print(converged)
        True
    """
    if previous_score <= 0:
        return False

    improvement = (current_score - previous_score) / previous_score
    # Only converge when improvement is small but non-negative.
    # If score decreased (improvement < 0), keep trying — don't stop early.
    converged = 0 <= improvement < threshold

    logger.info(
        f"Convergence check: score {previous_score:.3f} → {current_score:.3f} "
        f"(improvement: {improvement * 100:.1f}%, threshold: {threshold * 100:.1f}%) "
        f"→ {'CONVERGED' if converged else 'continue'}"
    )

    return converged
