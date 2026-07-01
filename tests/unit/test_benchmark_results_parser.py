# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for the benchmark results parser."""

import json
from pathlib import Path

import pytest

from dds_optimizer.benchmark.results_parser import parse_benchmark_results


SAMPLE_RESULT = {
    "BasicPerformanceMetrics.FIRST_SENT_RECEIVED_LATENCY": 9.37,
    "BasicPerformanceMetrics.LAST_SENT_RECEIVED_LATENCY": 10.60,
    "BasicPerformanceMetrics.MEAN_LATENCY": 9.85,
    "BasicPerformanceMetrics.MAX_LATENCY": 18.42,
    "BasicPerformanceMetrics.MEAN_FRAME_RATE": 104.84,
    "BasicPerformanceMetrics.MEAN_PLAYBACK_FRAME_RATE": 111.60,
    "BasicPerformanceMetrics.NUM_MISSED_FRAMES": 0.0,
    "BasicPerformanceMetrics.NUM_FRAMES_SENT": 557.0,
    "BasicPerformanceMetrics.MEAN_JITTER": 1.33,
    "BasicPerformanceMetrics.MAX_JITTER": 8.68,
    "ResourceMetrics.MEAN_OVERALL_CPU_UTILIZATION": 2.56,
    "ResourceMetrics.MAX_OVERALL_CPU_UTILIZATION": 14.58,
    "BenchmarkMetadata.PEAK_THROUGHPUT_PREDICTION": 111.4,
}


@pytest.fixture
def sample_result_file(tmp_path):
    """Create a temporary benchmark result JSON file."""
    result_file = tmp_path / "benchmark_result.json"
    result_file.write_text(json.dumps(SAMPLE_RESULT))
    return result_file


def test_parse_mean_latency(sample_result_file):
    """Test that mean latency is parsed correctly (uses MEAN_LATENCY when available)."""
    results = parse_benchmark_results(sample_result_file)
    assert results.mean_latency_ms == pytest.approx(9.85, rel=0.01)


def test_parse_max_latency(sample_result_file):
    """Test that max latency is parsed correctly."""
    results = parse_benchmark_results(sample_result_file)
    assert results.max_latency_ms == pytest.approx(18.42, rel=0.01)


def test_parse_p95_p99_from_max_latency(sample_result_file):
    """Test that p95/p99 use MAX_LATENCY when available."""
    results = parse_benchmark_results(sample_result_file)
    # When MAX_LATENCY is available, both p95 and p99 use it
    assert results.p95_latency_ms == pytest.approx(18.42, rel=0.01)
    assert results.p99_latency_ms == pytest.approx(18.42, rel=0.01)


def test_parse_throughput(sample_result_file):
    """Test that throughput (msgs/sec) is parsed correctly."""
    results = parse_benchmark_results(sample_result_file)
    assert results.msgs_per_sec == pytest.approx(104.84, rel=0.01)


def test_parse_zero_packet_loss(sample_result_file):
    """Test that zero packet loss is computed correctly."""
    results = parse_benchmark_results(sample_result_file)
    assert results.packet_loss_rate == pytest.approx(0.0, abs=1e-6)


def test_parse_cpu_usage(sample_result_file):
    """Test that CPU usage is parsed correctly."""
    results = parse_benchmark_results(sample_result_file)
    assert results.cpu_percent == pytest.approx(2.56, rel=0.01)


def test_parse_jitter(sample_result_file):
    """Test that jitter metrics are parsed correctly."""
    results = parse_benchmark_results(sample_result_file)
    assert results.mean_jitter_ms == pytest.approx(1.33, rel=0.01)
    assert results.max_jitter_ms == pytest.approx(8.68, rel=0.01)


def test_parse_fallback_latency(tmp_path):
    """Test latency estimation when MEAN_LATENCY is not available."""
    result_without_mean = {
        "BasicPerformanceMetrics.FIRST_SENT_RECEIVED_LATENCY": 9.0,
        "BasicPerformanceMetrics.LAST_SENT_RECEIVED_LATENCY": 11.0,
        "BasicPerformanceMetrics.NUM_MISSED_FRAMES": 5.0,
        "BasicPerformanceMetrics.NUM_FRAMES_SENT": 100.0,
    }
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps(result_without_mean))

    results = parse_benchmark_results(result_file)
    # Should average first and last latency
    assert results.mean_latency_ms == pytest.approx(10.0, rel=0.01)


def test_parse_packet_loss_rate(tmp_path):
    """Test packet loss rate computation."""
    result_with_loss = {
        "BasicPerformanceMetrics.NUM_MISSED_FRAMES": 10.0,
        "BasicPerformanceMetrics.NUM_FRAMES_SENT": 1000.0,
    }
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps(result_with_loss))

    results = parse_benchmark_results(result_file)
    assert results.packet_loss_rate == pytest.approx(0.01, rel=0.01)


def test_parse_missing_file():
    """Test that FileNotFoundError is raised for missing files."""
    with pytest.raises(FileNotFoundError):
        parse_benchmark_results(Path("/nonexistent/result.json"))


def test_parse_invalid_json(tmp_path):
    """Test that ValueError is raised for invalid JSON."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json {{{")
    with pytest.raises(ValueError):
        parse_benchmark_results(bad_file)


def test_parse_empty_result(tmp_path):
    """Test parsing an empty result (all metrics None)."""
    result_file = tmp_path / "empty.json"
    result_file.write_text("{}")
    results = parse_benchmark_results(result_file)

    assert results.mean_latency_ms is None
    assert results.msgs_per_sec is None
    assert results.packet_loss_rate is None
    assert results.cpu_percent is None


def test_parse_p95_p99_from_jitter(tmp_path):
    """Test p95/p99 estimation from jitter when MAX_LATENCY is not available."""
    result_with_jitter = {
        "BasicPerformanceMetrics.MEAN_LATENCY": 10.0,
        "BasicPerformanceMetrics.MEAN_JITTER": 2.0,
        "BasicPerformanceMetrics.MAX_JITTER": 5.0,
    }
    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps(result_with_jitter))

    results = parse_benchmark_results(result_file)
    # p95 ≈ mean + 2 * mean_jitter = 10 + 4 = 14
    assert results.p95_latency_ms == pytest.approx(14.0, rel=0.01)
    # p99 ≈ mean + 3 * max_jitter = 10 + 15 = 25
    assert results.p99_latency_ms == pytest.approx(25.0, rel=0.01)
