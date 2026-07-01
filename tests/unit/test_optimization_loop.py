# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for the optimizer evaluator and convergence check."""

import pytest

from dds_optimizer.models import BenchmarkResults, PerformanceRequirements
from dds_optimizer.optimizer.evaluator import (
    EvaluationResult,
    check_convergence,
    evaluate_results,
)


def make_requirements(
    latency_mean=10.0,
    latency_p95=15.0,
    latency_p99=20.0,
    latency_optional=False,
    throughput_msgs=1000.0,
    throughput_optional=True,
    loss_rate=0.001,
    loss_optional=False,
    cpu_max=50.0,
    cpu_optional=True,
):
    """Helper to create PerformanceRequirements for testing."""
    from dds_optimizer.models import (
        LatencyRequirement,
        ThroughputRequirement,
        ReliabilityRequirement,
        CpuUsageRequirement,
    )
    return PerformanceRequirements(
        latency=LatencyRequirement(
            target_mean_ms=latency_mean,
            target_p95_ms=latency_p95,
            target_p99_ms=latency_p99,
            optional=latency_optional,
        ),
        throughput=ThroughputRequirement(
            target_msgs_per_sec=throughput_msgs,
            optional=throughput_optional,
        ),
        reliability=ReliabilityRequirement(
            max_packet_loss_rate=loss_rate,
            optional=loss_optional,
        ),
        cpu_usage=CpuUsageRequirement(
            max_percent=cpu_max,
            optional=cpu_optional,
        ),
    )


def make_results(
    mean_latency=9.0,
    p95_latency=14.0,
    p99_latency=18.0,
    msgs_per_sec=1100.0,
    packet_loss=0.0,
    cpu_percent=30.0,
):
    """Helper to create BenchmarkResults for testing."""
    return BenchmarkResults(
        mean_latency_ms=mean_latency,
        p95_latency_ms=p95_latency,
        p99_latency_ms=p99_latency,
        msgs_per_sec=msgs_per_sec,
        packet_loss_rate=packet_loss,
        cpu_percent=cpu_percent,
    )


# -----------------------------------------------------------------------
# Test evaluate_results
# -----------------------------------------------------------------------

def test_all_requirements_met():
    """Test that all requirements are met when results are within targets."""
    requirements = make_requirements()
    results = make_results()
    eval_result = evaluate_results(results, requirements)

    assert eval_result.required_metrics_met is True
    assert eval_result.performance_score == pytest.approx(1.0, abs=0.01)
    assert eval_result.failed_required == []


def test_required_latency_failed():
    """Test that required latency failure is detected."""
    requirements = make_requirements(latency_mean=5.0, latency_optional=False)
    results = make_results(mean_latency=15.0)  # 3x over target
    eval_result = evaluate_results(results, requirements)

    assert eval_result.required_metrics_met is False
    assert "latency_mean_ms" in eval_result.failed_required


def test_optional_throughput_failed_does_not_fail_required():
    """Test that optional metric failure doesn't affect required_metrics_met."""
    requirements = make_requirements(throughput_msgs=2000.0, throughput_optional=True)
    results = make_results(msgs_per_sec=500.0)  # Below target
    eval_result = evaluate_results(results, requirements)

    # Required metrics (latency, reliability) are still met
    assert eval_result.required_metrics_met is True
    # But optional is not
    assert eval_result.optional_metrics_met is False
    assert "throughput_msgs_per_sec" in eval_result.failed_optional


def test_required_reliability_failed():
    """Test that required reliability failure is detected."""
    requirements = make_requirements(loss_rate=0.001, loss_optional=False)
    results = make_results(packet_loss=0.01)  # 10x over target
    eval_result = evaluate_results(results, requirements)

    assert eval_result.required_metrics_met is False
    assert "packet_loss_rate" in eval_result.failed_required


def test_performance_score_partial():
    """Test that performance score is between 0 and 1 for partial results."""
    requirements = make_requirements(latency_mean=5.0)
    results = make_results(mean_latency=10.0)  # 2x over target
    eval_result = evaluate_results(results, requirements)

    assert 0.0 < eval_result.performance_score < 1.0


def test_performance_score_perfect():
    """Test that performance score is 1.0 when all requirements are met."""
    requirements = make_requirements()
    results = make_results()
    eval_result = evaluate_results(results, requirements)

    assert eval_result.performance_score == pytest.approx(1.0, abs=0.01)


def test_missing_results_not_evaluated():
    """Test that metrics with None values are not evaluated."""
    requirements = make_requirements()
    results = BenchmarkResults(
        mean_latency_ms=None,
        msgs_per_sec=None,
        packet_loss_rate=None,
        cpu_percent=None,
    )
    eval_result = evaluate_results(results, requirements)

    # No metrics could be evaluated
    assert eval_result.metric_status == {}
    assert eval_result.performance_score == 0.0


# -----------------------------------------------------------------------
# Test check_convergence
# -----------------------------------------------------------------------

def test_convergence_detected():
    """Test that convergence is detected when improvement is below threshold."""
    # 2% improvement < 5% threshold → converged
    converged = check_convergence(
        current_score=0.95,
        previous_score=0.93,
        threshold=0.05,
    )
    assert converged is True


def test_no_convergence_large_improvement():
    """Test that convergence is not detected with large improvement."""
    # 20% improvement > 5% threshold → not converged
    converged = check_convergence(
        current_score=0.90,
        previous_score=0.75,
        threshold=0.05,
    )
    assert converged is False


def test_convergence_zero_previous_score():
    """Test that convergence is not detected when previous score is 0."""
    converged = check_convergence(
        current_score=0.5,
        previous_score=0.0,
        threshold=0.05,
    )
    assert converged is False


# -----------------------------------------------------------------------
# Test _run_optimization_loop termination logic (bug regression tests)
# -----------------------------------------------------------------------

def test_bug_convergence_check_unreachable(tmp_path):
    """
    BUG: convergence check in _run_optimization_loop is dead code (lines 389-402).

    The `if required_metrics_met: break` at line 377 always fires first when
    required_metrics_met=True. The convergence check at line 389 also requires
    required_metrics_met=True, but at that point required_metrics_met is always
    False (otherwise we already broke out) — a logical contradiction making the
    convergence check unreachable.

    EXPECTED (after fix):
    When required_metrics_met=True but all_metrics_met=False, the loop should
    continue optimizing optional metrics. Once the score improvement drops below
    the convergence threshold, session.converged should be set to True.

    CURRENT (buggy):
    session.converged is never set — the loop breaks immediately at iter 1
    when required_metrics_met=True, never reaching the convergence check.
    """
    from unittest.mock import MagicMock, patch

    from dds_optimizer.models import (
        BenchmarkConfig,
        BenchmarkResults,
        DDSParameterSet,
        EnvironmentInfo,
        LLMConfig,
        OptimizationSession,
        OptimizationSettings,
        RequirementsConfig,
    )
    from dds_optimizer.optimizer.optimization_loop import _run_optimization_loop

    # Requirements: 5 max iterations, 5% convergence threshold
    requirements = RequirementsConfig(
        benchmark=BenchmarkConfig(test_file="/fake/test.py"),
        performance_requirements=make_requirements(
            throughput_optional=True,  # throughput is optional → all_metrics_met=False when not hit
        ),
        optimization_settings=OptimizationSettings(
            max_iterations=5,
            convergence_threshold=0.05,
        ),
        llm_config=LLMConfig(),
    )
    session = OptimizationSession()
    env = EnvironmentInfo(os_version="Ubuntu 24.04", ros2_distro="jazzy")

    # Iter 1: required met, optional NOT met, score=0.90
    # Iter 2: required met, optional NOT met, score=0.91 → improvement 1.1% < 5% → should converge
    eval_iter1 = MagicMock(spec=EvaluationResult)
    eval_iter1.required_metrics_met = True
    eval_iter1.all_metrics_met = False
    eval_iter1.optional_metrics_met = False
    eval_iter1.performance_score = 0.90
    eval_iter1.failed_required = []
    eval_iter1.failed_optional = ["throughput_msgs_per_sec"]

    eval_iter2 = MagicMock(spec=EvaluationResult)
    eval_iter2.required_metrics_met = True
    eval_iter2.all_metrics_met = False
    eval_iter2.optional_metrics_met = False
    eval_iter2.performance_score = 0.91
    eval_iter2.failed_required = []
    eval_iter2.failed_optional = ["throughput_msgs_per_sec"]

    dummy_results = BenchmarkResults(
        mean_latency_ms=9.0, p95_latency_ms=14.0, p99_latency_ms=18.0,
        msgs_per_sec=800.0, packet_loss_rate=0.0, cpu_percent=30.0,
    )
    dummy_param_set = DDSParameterSet(parameters={}, delete_params=[], reasoning="test")
    dummy_config_path = tmp_path / "epoch_1" / "fastdds_config.xml"
    dummy_config_path.parent.mkdir(parents=True)

    mock_backend = MagicMock()
    mock_backend.generate_config.return_value = dummy_config_path
    mock_backend.profiles_env_var = "FASTRTPS_DEFAULT_PROFILES_FILE"
    mock_backend.rmw_implementation = "rmw_fastrtps_cpp"
    mock_backend.name = "fastdds"
    module = "dds_optimizer.optimizer.optimization_loop"
    with (
        patch(f"{module}.run_benchmark", return_value=(tmp_path / "result.json", None)),
        patch(f"{module}.parse_benchmark_results", return_value=dummy_results),
        patch(f"{module}.evaluate_results", side_effect=[eval_iter1, eval_iter2]),
        patch(f"{module}.get_backend", return_value=mock_backend),
        patch(
            f"{module}._generate_config_with_llm",
            return_value=(dummy_param_set, "prompt", "response"),
        ),
        patch(f"{module}._save_session_state"),
        patch(f"{module}._save_llm_conversation"),
        patch(f"{module}.get_config_path", return_value=dummy_config_path),
        patch(f"{module}.get_epoch_dir", return_value=tmp_path),
        patch(f"{module}.get_final_config_path", return_value=tmp_path / "best.xml"),
        patch(f"{module}.write_json_atomic"),
        patch("shutil.copy2"),
    ):
        result_session = _run_optimization_loop(
            session=session,
            requirements=requirements,
            env=env,
            session_dir=tmp_path,
            initial_config_path="/fake/initial_config.xml",
        )

    # ASSERTION: After fix, the loop should continue past iter 1 and converge at iter 2
    # (score improvement 1.1% < 5% threshold while required metrics met).
    # With the BUG, the loop breaks at iter 1 (required_metrics_met=True → break),
    # and session.converged is never set to True.
    assert result_session.converged is True, (
        "BUG: convergence check is dead code. The `if required_metrics_met: break` "
        "at line 377 fires before the convergence check at line 389 can be reached. "
        "session.converged is never True even when scores plateau with required metrics met."
    )
    assert len(result_session.iterations) >= 2, (
        "BUG: loop should run multiple iterations when required_metrics_met=True "
        "but all_metrics_met=False, to allow convergence on optional metrics."
    )


def test_convergence_exact_threshold():
    """Test convergence at exactly the threshold boundary."""
    # Exactly 5% improvement = threshold → converged (< is False, so not converged)
    converged = check_convergence(
        current_score=1.05,
        previous_score=1.0,
        threshold=0.05,
    )
    # improvement = 5% = threshold → NOT converged (strictly less than)
    assert converged is False
