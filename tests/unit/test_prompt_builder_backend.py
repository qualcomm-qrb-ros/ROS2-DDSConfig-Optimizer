# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""The feedback prompt must reflect the selected backend (KB + wording)."""

from dds_optimizer.backends.registry import get_backend
from dds_optimizer.llm.prompt_builder import build_feedback_prompt
from dds_optimizer.models import (
    BenchmarkConfig,
    EnvironmentInfo,
    LatencyRequirement,
    PerformanceRequirements,
    RequirementsConfig,
)


def _reqs() -> RequirementsConfig:
    return RequirementsConfig(
        benchmark=BenchmarkConfig(test_file="/tmp/b.py"),
        performance_requirements=PerformanceRequirements(
            latency=LatencyRequirement(optional=False, target_mean_ms=10.0)
        ),
    )


def _env() -> EnvironmentInfo:
    return EnvironmentInfo(os_version="Ubuntu 24.04", ros2_distro="jazzy")


def test_cyclonedds_prompt_uses_cyclone_wording_and_params():
    prompt = build_feedback_prompt(
        requirements=_reqs(),
        env=_env(),
        current_config_params={},
        results=None,
        performance_gaps={},
        iteration=2,
        backend=get_backend("cyclonedds"),
    )
    assert "CycloneDDS" in prompt
    assert "ack_delay" in prompt              # a CycloneDDS KB param
    assert "Available cyclonedds Parameters" in prompt


def test_fastdds_prompt_uses_fastdds_params():
    prompt = build_feedback_prompt(
        requirements=_reqs(),
        env=_env(),
        current_config_params={},
        results=None,
        performance_gaps={},
        iteration=2,
        backend=get_backend("fastdds"),
    )
    assert "FastDDS" in prompt
    assert "Available fastdds Parameters" in prompt
