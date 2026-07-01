# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Shared Pydantic data models used across all modules of the FastDDS optimizer.

These models represent the core data structures for:
- User requirements (parsed from user_requirements.xml)
- Environment information (collected from the system)
- Benchmark results (parsed from ros2_benchmark JSON output)
- Optimization session state (tracking iterations and progress)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Performance Requirement Models
# ---------------------------------------------------------------------------

class LatencyRequirement(BaseModel):
    """
    End-to-end latency requirements.

    Attributes:
        optional: If False, this requirement MUST be met. If True, it is a nice-to-have.
        target_mean_ms: Target mean end-to-end latency in milliseconds.
        target_p95_ms: Target 95th percentile latency in milliseconds.
        target_p99_ms: Target 99th percentile latency in milliseconds.
    """
    optional: bool = False
    target_mean_ms: Optional[float] = None
    target_p95_ms: Optional[float] = None
    target_p99_ms: Optional[float] = None


class ThroughputRequirement(BaseModel):
    """
    Message throughput requirements.

    Attributes:
        optional: If False, this requirement MUST be met.
        target_msgs_per_sec: Target message rate in messages per second (fps).
        target_mbps: Target data throughput in megabits per second.
    """
    optional: bool = True
    target_msgs_per_sec: Optional[float] = None
    target_mbps: Optional[float] = None


class ReliabilityRequirement(BaseModel):
    """
    Message delivery reliability requirements.

    Attributes:
        optional: If False, this requirement MUST be met.
        max_packet_loss_rate: Maximum acceptable packet loss rate (0.0 to 1.0).
                              e.g., 0.001 means at most 0.1% packet loss.
    """
    optional: bool = False
    max_packet_loss_rate: Optional[float] = None

    @field_validator("max_packet_loss_rate")
    @classmethod
    def validate_loss_rate(cls, v: Optional[float]) -> Optional[float]:
        """Ensure packet loss rate is between 0 and 1."""
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"max_packet_loss_rate must be between 0.0 and 1.0, got {v}")
        return v


class CpuUsageRequirement(BaseModel):
    """
    CPU usage requirements.

    Attributes:
        optional: If False, this requirement MUST be met.
        max_percent: Maximum acceptable mean CPU utilization percentage (0-100).
    """
    optional: bool = True
    max_percent: Optional[float] = None


class MemoryUsageRequirement(BaseModel):
    """
    Memory usage requirements.

    Attributes:
        optional: If False, this requirement MUST be met.
        max_mb: Maximum acceptable memory usage in megabytes.
    """
    optional: bool = True
    max_mb: Optional[float] = None


class PerformanceRequirements(BaseModel):
    """
    Aggregated performance requirements from user_requirements.xml.

    Contains all performance targets with their optional/required flags.
    """
    latency: Optional[LatencyRequirement] = None
    throughput: Optional[ThroughputRequirement] = None
    reliability: Optional[ReliabilityRequirement] = None
    cpu_usage: Optional[CpuUsageRequirement] = None
    memory_usage: Optional[MemoryUsageRequirement] = None


# ---------------------------------------------------------------------------
# Benchmark Configuration Model
# ---------------------------------------------------------------------------

class BenchmarkConfig(BaseModel):
    """
    Configuration for the benchmark test to run.

    Attributes:
        test_file: Absolute path to the ros2_benchmark test script (.py file).
        launch_command: Command to use for launching the test (default: 'launch_test').
    """
    test_file: str
    launch_command: str = "launch_test"


# ---------------------------------------------------------------------------
# Optimization Settings Model
# ---------------------------------------------------------------------------

class OptimizationSettings(BaseModel):
    """
    Settings that control the optimization loop behavior.

    Attributes:
        max_iterations: Maximum number of LLM-driven optimization iterations.
        convergence_threshold: Stop iterating if improvement is less than this fraction.
                               e.g., 0.05 means stop if improvement < 5%.
    """
    max_iterations: int = Field(default=5, ge=1, le=50)
    convergence_threshold: float = Field(default=0.05, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# LLM Configuration Model
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    """
    Configuration for the LLM API used to generate DDS parameter suggestions.

    Attributes:
        provider: LLM provider name ('openai', 'anthropic', or 'plugin').
                  When 'plugin' is used, plugin_module must be specified.
        model: Model identifier (e.g., 'gpt-4', 'claude-3-opus-20240229').
        base_url: API base URL. Allows using custom/proxy endpoints.
        api_key_env: Name of the environment variable containing the API key.
        plugin_module: Python module path for a custom LLM provider plugin.
                       When set, the provider field is ignored and the plugin
                       is loaded dynamically. The module must implement a
                       call_provider(prompt, config, api_key) -> str function.
    """
    provider: str = "openrouter"
    model: str = "openrouter/free"
    base_url: Optional[str] = None
    api_key_env: str = "LLM_API_KEY"
    plugin_module: Optional[str] = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Ensure provider is one of the supported options."""
        supported = {"openai", "anthropic", "openrouter", "plugin"}
        if v.lower() not in supported:
            raise ValueError(
                f"Unsupported LLM provider '{v}'. Must be one of: {supported}"
            )
        return v.lower()


# ---------------------------------------------------------------------------
# Top-Level Requirements Config Model
# ---------------------------------------------------------------------------

class RequirementsConfig(BaseModel):
    """
    Complete parsed content of user_requirements.xml.

    This is the top-level model that holds all user-provided configuration
    for a single optimization run.
    """
    benchmark: BenchmarkConfig
    performance_requirements: PerformanceRequirements
    optimization_settings: OptimizationSettings = Field(default_factory=OptimizationSettings)
    llm_config: LLMConfig = Field(default_factory=LLMConfig)


# ---------------------------------------------------------------------------
# Environment Information Models
# ---------------------------------------------------------------------------

class CpuInfo(BaseModel):
    """
    CPU hardware information (collected when cpu_usage requirement is present).

    Attributes:
        cores_physical: Number of physical CPU cores.
        cores_logical: Number of logical CPU cores (including hyperthreading).
        model: CPU model name string.
        frequency_mhz: Current CPU frequency in MHz.
    """
    cores_physical: int
    cores_logical: int
    model: str
    frequency_mhz: Optional[float] = None


class MemoryInfo(BaseModel):
    """
    System memory information (collected when memory_usage requirement is present).

    Attributes:
        total_mb: Total system RAM in megabytes.
        available_mb: Currently available RAM in megabytes.
        used_percent: Percentage of RAM currently in use.
    """
    total_mb: float
    available_mb: float
    used_percent: float


class TopicInfo(BaseModel):
    """
    Information about a single ROS2 topic.

    Attributes:
        name: Topic name (e.g., '/camera/image_raw').
        msg_type: ROS2 message type (e.g., 'sensor_msgs/msg/Image').
        publisher_count: Number of publishers on this topic.
        subscriber_count: Number of subscribers on this topic.
    """
    name: str
    msg_type: str
    publisher_count: int = 0
    subscriber_count: int = 0


class EnvironmentInfo(BaseModel):
    """
    System environment information collected before optimization.

    Minimum required fields are always collected. CPU and memory info
    are only collected when the corresponding requirements are present.
    """
    # Always collected
    os_version: str                          # e.g., "Ubuntu 24.04.1 LTS"
    ros2_distro: str                         # e.g., "jazzy"
    active_nodes: List[str] = Field(default_factory=list)   # from 'ros2 node list'
    active_topics: List[TopicInfo] = Field(default_factory=list)  # from 'ros2 topic list -t'

    # Conditionally collected
    cpu_info: Optional[CpuInfo] = None       # collected if cpu_usage requirement present
    memory_info: Optional[MemoryInfo] = None  # collected if memory_usage requirement present

    # Collection timestamp
    collected_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Benchmark Results Model
# ---------------------------------------------------------------------------

class BenchmarkResults(BaseModel):
    """
    Parsed performance metrics from a ros2_benchmark JSON output file.

    Metrics are mapped from the ros2_benchmark JSON keys:
    - FIRST_SENT_RECEIVED_LATENCY + LAST_SENT_RECEIVED_LATENCY → mean_latency_ms
    - MEAN_FRAME_RATE → msgs_per_sec
    - NUM_MISSED_FRAMES / NUM_FRAMES_SENT → packet_loss_rate
    - MEAN_OVERALL_CPU_UTILIZATION → cpu_percent
    """
    # Latency metrics (milliseconds)
    mean_latency_ms: Optional[float] = None    # Average of first+last sent-received latency
    p95_latency_ms: Optional[float] = None     # 95th percentile estimate
    p99_latency_ms: Optional[float] = None     # 99th percentile estimate (uses MAX_LATENCY)
    max_latency_ms: Optional[float] = None     # Maximum observed latency

    # Throughput metrics
    msgs_per_sec: Optional[float] = None       # Mean output frame rate (fps = msgs/sec)
    peak_msgs_per_sec: Optional[float] = None  # Peak throughput prediction

    # Reliability metrics
    packet_loss_rate: Optional[float] = None   # NUM_MISSED_FRAMES / NUM_FRAMES_SENT
    num_missed_frames: Optional[float] = None
    num_frames_sent: Optional[float] = None

    # Resource metrics
    cpu_percent: Optional[float] = None        # Mean overall CPU utilization %
    max_cpu_percent: Optional[float] = None    # Max CPU utilization %
    memory_mb: Optional[float] = None          # Mean process memory usage in MB

    # Jitter metrics (milliseconds)
    mean_jitter_ms: Optional[float] = None
    max_jitter_ms: Optional[float] = None

    # Raw JSON data from ros2_benchmark for full access
    raw_data: Dict[str, Any] = Field(default_factory=dict)

    # Path to the JSON result file
    result_file_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline Topology Models (collected during benchmark run)
# ---------------------------------------------------------------------------

class TopicConnection(BaseModel):
    """
    Information about a single ROS2 topic including its publisher and subscriber nodes.

    Attributes:
        name: Topic name (e.g., '/camera/image_raw').
        msg_type: ROS2 message type (e.g., 'sensor_msgs/msg/Image').
        publishers: List of node full paths that publish to this topic (e.g. '/publisher').
        subscribers: List of node full paths that subscribe to this topic.
        msg_size_bytes: Average serialized message size in bytes (measured during benchmark).
        qos_reliability: Reliability QoS of the publisher ('RELIABLE' or 'BEST_EFFORT').
        qos_durability: Durability QoS of the publisher ('VOLATILE' or 'TRANSIENT_LOCAL').
    """
    name: str
    msg_type: str
    publishers: List[str] = Field(default_factory=list)
    subscribers: List[str] = Field(default_factory=list)
    msg_size_bytes: Optional[float] = None
    qos_reliability: Optional[str] = None
    qos_durability: Optional[str] = None


class PipelineTopology(BaseModel):
    """
    Snapshot of the running ROS2 pipeline topology collected during a benchmark run.

    Captures the full pipeline graph: which nodes are active, which topics exist,
    which nodes publish/subscribe to each topic, and which nodes share a process.

    Attributes:
        nodes: List of active pipeline node full paths (infrastructure nodes filtered out).
        topics: List of TopicConnection objects with publisher/subscriber info.
        process_groups: Maps container/process name to the list of nodes it hosts.
                        Nodes NOT in any component container appear as standalone entries.
                        Empty dict means process co-location could not be determined.
        collected_at: When this snapshot was taken.
    """
    nodes: List[str] = Field(default_factory=list)
    topics: List[TopicConnection] = Field(default_factory=list)
    process_groups: Dict[str, List[str]] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# DDS Parameter Value Model
# ---------------------------------------------------------------------------

class DDSParameterSet(BaseModel):
    """
    FastDDS parameter values generated by the LLM.

    The LLM outputs a structured JSON object with two keys:
    - "set": dict of parameter name → value to apply
    - "delete": list of parameter names to revert to system defaults

    The system generates the complete FastDDS XML config from these parameters
    using config/generator.py.

    Attributes:
        parameters: Dict of parameter name → value (e.g. {"history_depth": 10}).
                    Only parameters the LLM wants to set/override.
                    Must only contain names from fastdds_config_template.xml.
        delete_params: List of parameter names to remove from the accumulated
                       params dict (revert to template defaults).
        reasoning:  LLM's explanation for the parameter choices.
        xml_content: (legacy) kept for backward compatibility; not used in the
                     new JSON-params flow.

    Example:
        parameters = {"intraprocess_delivery": "FULL", "history_depth": 1}
        delete_params = ["udp_send_buffer_size"]
    """
    parameters: Dict[str, Any] = Field(default_factory=dict)   # LLM-provided param overrides
    delete_params: List[str] = Field(default_factory=list)      # params to revert to defaults
    reasoning: Optional[str] = None                             # LLM's explanation
    xml_content: str = ""                                       # legacy field (unused)


# ---------------------------------------------------------------------------
# Optimization Iteration Model
# ---------------------------------------------------------------------------

class OptimizationIteration(BaseModel):
    """
    Record of a single optimization iteration.

    Tracks the config used, benchmark results obtained, and whether
    requirements were met in this iteration.
    """
    iteration_number: int
    config_path: str                          # Path to the FastDDS XML config used
    results: Optional[BenchmarkResults] = None
    requirements_met: bool = False
    required_metrics_met: bool = False        # All non-optional requirements met
    optional_metrics_met: bool = False        # All optional requirements met
    performance_score: float = 0.0           # Composite score (higher = better)
    timestamp: datetime = Field(default_factory=datetime.now)
    llm_reasoning: Optional[str] = None      # LLM's reasoning for this iteration
    benchmark_error: Optional[str] = None    # Error message if benchmark failed
    pipeline_topology: Optional[PipelineTopology] = None  # Pipeline graph during benchmark
    params_set: Dict[str, Any] = Field(default_factory=dict)    # params applied in this epoch
    params_deleted: List[str] = Field(default_factory=list)     # params reverted in this epoch


# ---------------------------------------------------------------------------
# Optimization Session Model
# ---------------------------------------------------------------------------

class OptimizationSession(BaseModel):
    """
    Complete record of an optimization session.

    A session encompasses all iterations from initial LLM config generation
    through the final optimized configuration.
    """
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Input configuration
    requirements: Optional[RequirementsConfig] = None
    environment: Optional[EnvironmentInfo] = None

    # Iteration history
    iterations: List[OptimizationIteration] = Field(default_factory=list)

    # Final outcome
    best_iteration: Optional[int] = None     # Index of best iteration
    final_config_path: Optional[str] = None  # Path to final optimized config
    converged: bool = False
    success: bool = False                    # True if all required metrics were met

    def get_best_iteration(self) -> Optional[OptimizationIteration]:
        """Return the iteration with the highest performance score."""
        if not self.iterations:
            return None
        return max(self.iterations, key=lambda it: it.performance_score)

    def get_latest_results(self) -> Optional[BenchmarkResults]:
        """Return benchmark results from the most recent iteration."""
        if not self.iterations:
            return None
        return self.iterations[-1].results
