# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Benchmark Results Parser: parses ros2_benchmark JSON output into BenchmarkResults.

ros2_benchmark writes results to a JSON file with this structure:
{
    "BasicPerformanceMetrics.FIRST_SENT_RECEIVED_LATENCY": 9.37,   // ms
    "BasicPerformanceMetrics.LAST_SENT_RECEIVED_LATENCY": 10.60,   // ms
    "BasicPerformanceMetrics.MEAN_LATENCY": ...,                    // ms (if message_key_match=True)
    "BasicPerformanceMetrics.MAX_LATENCY": ...,                     // ms (if message_key_match=True)
    "BasicPerformanceMetrics.MEAN_FRAME_RATE": 104.84,             // fps = msgs/sec
    "BasicPerformanceMetrics.MEAN_PLAYBACK_FRAME_RATE": 111.60,    // fps input rate
    "BasicPerformanceMetrics.NUM_MISSED_FRAMES": 33.67,
    "BasicPerformanceMetrics.NUM_FRAMES_SENT": 557.0,
    "BasicPerformanceMetrics.MEAN_JITTER": 1.33,                   // ms
    "BasicPerformanceMetrics.MAX_JITTER": 8.68,                    // ms
    "ResourceMetrics.MEAN_OVERALL_CPU_UTILIZATION": 2.56,          // %
    "ResourceMetrics.MAX_OVERALL_CPU_UTILIZATION": 14.58,          // %
    "BenchmarkMetadata.PEAK_THROUGHPUT_PREDICTION": 111.4,         // fps
    "metadata": { ... }
}

Metric mapping to our requirements:
    latency.target_mean_ms  → avg(FIRST_SENT_RECEIVED_LATENCY, LAST_SENT_RECEIVED_LATENCY)
                              or MEAN_LATENCY if available
    latency.target_p95_ms   → MAX_LATENCY if available, else mean + 2*mean_jitter
    latency.target_p99_ms   → MAX_LATENCY if available, else mean + 3*max_jitter
    throughput.msgs_per_sec → MEAN_FRAME_RATE
    reliability.loss_rate   → NUM_MISSED_FRAMES / NUM_FRAMES_SENT
    cpu_usage.percent       → MEAN_OVERALL_CPU_UTILIZATION
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..models import BenchmarkResults
from ..utils.logger import get_logger

logger = get_logger(__name__)

# ros2_benchmark JSON key constants
KEY_FIRST_LATENCY = "BasicPerformanceMetrics.FIRST_SENT_RECEIVED_LATENCY"
KEY_LAST_LATENCY = "BasicPerformanceMetrics.LAST_SENT_RECEIVED_LATENCY"
KEY_MEAN_LATENCY = "BasicPerformanceMetrics.MEAN_LATENCY"
KEY_MAX_LATENCY = "BasicPerformanceMetrics.MAX_LATENCY"
KEY_MEAN_FRAME_RATE = "BasicPerformanceMetrics.MEAN_FRAME_RATE"
KEY_MEAN_PLAYBACK_RATE = "BasicPerformanceMetrics.MEAN_PLAYBACK_FRAME_RATE"
KEY_NUM_MISSED_FRAMES = "BasicPerformanceMetrics.NUM_MISSED_FRAMES"
KEY_NUM_FRAMES_SENT = "BasicPerformanceMetrics.NUM_FRAMES_SENT"
KEY_MEAN_JITTER = "BasicPerformanceMetrics.MEAN_JITTER"
KEY_MAX_JITTER = "BasicPerformanceMetrics.MAX_JITTER"
KEY_MEAN_CPU = "ResourceMetrics.MEAN_OVERALL_CPU_UTILIZATION"
KEY_MAX_CPU = "ResourceMetrics.MAX_OVERALL_CPU_UTILIZATION"
KEY_PEAK_THROUGHPUT = "BenchmarkMetadata.PEAK_THROUGHPUT_PREDICTION"
KEY_MEAN_MEMORY_MB = "ResourceMetrics.MEAN_MEMORY_UTILIZATION"


def parse_benchmark_results(result_json_path: Path) -> BenchmarkResults:
    """
    Parse a ros2_benchmark JSON result file into a BenchmarkResults model.

    This is the main entry point for result parsing. It reads the JSON file,
    extracts all relevant metrics, and returns a typed BenchmarkResults model.

    Latency estimation strategy:
    - If MEAN_LATENCY is available (requires message_key_match=True in benchmark config):
      Use it directly for mean_latency_ms
    - Otherwise: average FIRST_SENT_RECEIVED_LATENCY and LAST_SENT_RECEIVED_LATENCY
    - For p95/p99: use MAX_LATENCY if available, otherwise estimate from jitter

    Args:
        result_json_path: Path to the ros2_benchmark JSON result file.

    Returns:
        BenchmarkResults with all extracted metrics.

    Raises:
        FileNotFoundError: If the result file does not exist.
        ValueError: If the JSON file is malformed or missing required fields.

    Example:
        >>> results = parse_benchmark_results(Path("/tmp/benchmark_result_001.json"))
        >>> print(f"Mean latency: {results.mean_latency_ms:.2f}ms")
        >>> print(f"Throughput: {results.msgs_per_sec:.1f} msgs/sec")
        >>> print(f"Packet loss: {results.packet_loss_rate * 100:.3f}%")
    """
    if not result_json_path.exists():
        raise FileNotFoundError(f"Benchmark result file not found: {result_json_path}")

    # Load JSON
    try:
        with open(result_json_path) as f:
            data: Dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse benchmark result JSON: {e}. "
            f"File: {result_json_path}"
        ) from e

    logger.debug(f"Parsing benchmark results from: {result_json_path}")

    # -----------------------------------------------------------------------
    # Flatten nested pipeline metrics into the top-level dict.
    # ros2_benchmark may nest per-pipeline metrics under a key like
    # "inter_process_pipeline" while CPU/resource metrics stay at the top level.
    # We merge all nested dicts (except "custom" and "metadata") into a flat
    # lookup dict so the rest of the parser can use simple key lookups.
    # -----------------------------------------------------------------------
    flat: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, dict) and k not in ("custom", "metadata"):
            flat.update(v)
        else:
            flat[k] = v

    # -----------------------------------------------------------------------
    # Extract latency metrics
    # -----------------------------------------------------------------------
    mean_latency_ms = _extract_mean_latency(flat)
    max_latency_ms = _safe_float(flat, KEY_MAX_LATENCY)
    mean_jitter_ms = _safe_float(flat, KEY_MEAN_JITTER)
    max_jitter_ms = _safe_float(flat, KEY_MAX_JITTER)

    # Estimate p95 and p99 latency
    p95_latency_ms, p99_latency_ms = _estimate_percentile_latencies(
        mean_latency_ms=mean_latency_ms,
        max_latency_ms=max_latency_ms,
        mean_jitter_ms=mean_jitter_ms,
        max_jitter_ms=max_jitter_ms,
    )

    # -----------------------------------------------------------------------
    # Extract throughput metrics
    # -----------------------------------------------------------------------
    msgs_per_sec = _safe_float(flat, KEY_MEAN_FRAME_RATE)
    peak_msgs_per_sec = _safe_float(flat, KEY_PEAK_THROUGHPUT)

    # -----------------------------------------------------------------------
    # Extract reliability metrics (packet loss)
    # -----------------------------------------------------------------------
    num_missed = _safe_float(flat, KEY_NUM_MISSED_FRAMES)
    num_sent = _safe_float(flat, KEY_NUM_FRAMES_SENT)
    packet_loss_rate = _compute_packet_loss_rate(num_missed, num_sent)

    # -----------------------------------------------------------------------
    # Extract CPU metrics
    # -----------------------------------------------------------------------
    cpu_percent = _safe_float(flat, KEY_MEAN_CPU)
    max_cpu_percent = _safe_float(flat, KEY_MAX_CPU)

    # -----------------------------------------------------------------------
    # Extract memory metrics (MB) — present only if the benchmark reports it
    # -----------------------------------------------------------------------
    memory_mb = _safe_float(flat, KEY_MEAN_MEMORY_MB)

    results = BenchmarkResults(
        mean_latency_ms=mean_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        max_latency_ms=max_latency_ms,
        msgs_per_sec=msgs_per_sec,
        peak_msgs_per_sec=peak_msgs_per_sec,
        packet_loss_rate=packet_loss_rate,
        num_missed_frames=num_missed,
        num_frames_sent=num_sent,
        cpu_percent=cpu_percent,
        max_cpu_percent=max_cpu_percent,
        memory_mb=memory_mb,
        mean_jitter_ms=mean_jitter_ms,
        max_jitter_ms=max_jitter_ms,
        raw_data=data,
        result_file_path=str(result_json_path),
    )

    _log_results_summary(results)
    return results


def _safe_float(data: Dict[str, Any], key: str) -> Optional[float]:
    """
    Safely extract a float value from the results dictionary.

    Args:
        data: The parsed JSON dictionary.
        key: The key to look up.

    Returns:
        Float value if found and valid, None otherwise.
    """
    value = data.get(key)
    if value is None:
        return None
    try:
        f = float(value)
        # Filter out NaN and infinity
        if f != f or f == float("inf") or f == float("-inf"):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _extract_mean_latency(data: Dict[str, Any]) -> Optional[float]:
    """
    Extract mean latency from the benchmark results.

    Strategy:
    1. Use MEAN_LATENCY if available (most accurate, requires message_key_match=True)
    2. Otherwise average FIRST_SENT_RECEIVED_LATENCY and LAST_SENT_RECEIVED_LATENCY

    Args:
        data: Parsed benchmark JSON data.

    Returns:
        Mean latency in milliseconds, or None if not available.
    """
    # Try MEAN_LATENCY first (most accurate)
    mean_latency = _safe_float(data, KEY_MEAN_LATENCY)
    if mean_latency is not None:
        logger.debug(f"Using MEAN_LATENCY: {mean_latency:.2f}ms")
        return mean_latency

    # Fall back to averaging first and last sent-received latency
    first_lat = _safe_float(data, KEY_FIRST_LATENCY)
    last_lat = _safe_float(data, KEY_LAST_LATENCY)

    if first_lat is not None and last_lat is not None:
        avg = (first_lat + last_lat) / 2.0
        logger.debug(
            f"Estimated mean latency from first({first_lat:.2f}ms) + "
            f"last({last_lat:.2f}ms) = {avg:.2f}ms"
        )
        return avg
    elif first_lat is not None:
        return first_lat
    elif last_lat is not None:
        return last_lat

    return None


def _estimate_percentile_latencies(
    mean_latency_ms: Optional[float],
    max_latency_ms: Optional[float],
    mean_jitter_ms: Optional[float],
    max_jitter_ms: Optional[float],
) -> tuple:
    """
    Estimate p95 and p99 latency percentiles.

    Strategy:
    - If MAX_LATENCY is available: use it as a conservative upper bound for both p95 and p99
    - Otherwise estimate using jitter:
        p95 ≈ mean + 2 * mean_jitter  (2-sigma approximation)
        p99 ≈ mean + 3 * max_jitter   (conservative estimate)

    Args:
        mean_latency_ms: Mean latency in ms.
        max_latency_ms: Maximum observed latency in ms (from ros2_benchmark).
        mean_jitter_ms: Mean jitter in ms.
        max_jitter_ms: Maximum jitter in ms.

    Returns:
        Tuple of (p95_latency_ms, p99_latency_ms), either may be None.
    """
    # If MAX_LATENCY is available, use it as upper bound
    if max_latency_ms is not None:
        return max_latency_ms, max_latency_ms

    # Estimate from jitter if mean latency is available
    if mean_latency_ms is not None:
        p95 = None
        p99 = None

        if mean_jitter_ms is not None:
            p95 = mean_latency_ms + 2.0 * mean_jitter_ms

        if max_jitter_ms is not None:
            p99 = mean_latency_ms + 3.0 * max_jitter_ms
        elif mean_jitter_ms is not None:
            p99 = mean_latency_ms + 3.0 * mean_jitter_ms

        return p95, p99

    return None, None


def _compute_packet_loss_rate(
    num_missed: Optional[float],
    num_sent: Optional[float],
) -> Optional[float]:
    """
    Compute packet loss rate from missed and sent frame counts.

    Args:
        num_missed: Number of missed/dropped frames.
        num_sent: Total number of frames sent.

    Returns:
        Packet loss rate as a fraction (0.0 to 1.0), or None if not available.
    """
    if num_missed is None or num_sent is None:
        return None
    if num_sent <= 0:
        return 0.0
    return max(0.0, min(1.0, num_missed / num_sent))


def _log_results_summary(results: BenchmarkResults) -> None:
    """Log a summary of the parsed benchmark results."""
    lines = ["Benchmark results summary:"]

    if results.mean_latency_ms is not None:
        lines.append(f"  Mean latency:  {results.mean_latency_ms:.2f}ms")
    if results.p95_latency_ms is not None:
        lines.append(f"  P95 latency:   {results.p95_latency_ms:.2f}ms")
    if results.p99_latency_ms is not None:
        lines.append(f"  P99 latency:   {results.p99_latency_ms:.2f}ms")
    if results.msgs_per_sec is not None:
        lines.append(f"  Throughput:    {results.msgs_per_sec:.1f} msgs/sec")
    if results.packet_loss_rate is not None:
        lines.append(f"  Packet loss:   {results.packet_loss_rate * 100:.4f}%")
    if results.cpu_percent is not None:
        lines.append(f"  CPU usage:     {results.cpu_percent:.1f}%")
    if results.memory_mb is not None:
        lines.append(f"  Memory usage:  {results.memory_mb:.1f}MB")
    if results.mean_jitter_ms is not None:
        lines.append(f"  Mean jitter:   {results.mean_jitter_ms:.2f}ms")

    logger.info("\n".join(lines))
