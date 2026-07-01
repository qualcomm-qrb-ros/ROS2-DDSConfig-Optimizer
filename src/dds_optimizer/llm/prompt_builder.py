# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Prompt Builder: constructs structured prompts for the LLM to generate FastDDS configurations.

The prompt includes:
1. System context: role, task description, output format instructions
   - Parameter operation rules: set (only from template), delete (by name)
2. Performance-critical parameter reference (from performance_critical_params.json)
   - Full descriptions, no truncation
3. Environment info: OS, ROS2 distro, active nodes/topics, hardware
4. Performance requirements: targets with optional/required flags
5. Recent optimization history:
   - Last 2 epochs: full details (gaps, strategy, effectiveness, params used)
   - Older epochs: one-line summary
6. Current benchmark results and performance gaps
7. Current FastDDS parameter values (accumulated from all past LLM epochs)
8. Pipeline topology (collected during the benchmark run)
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..models import (
    BenchmarkResults,
    EnvironmentInfo,
    OptimizationIteration,
    PerformanceRequirements,
    PipelineTopology,
    RequirementsConfig,
)

# Path to the performance-critical parameters knowledge base
_KNOWLEDGE_BASE_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "data"
    / "knowledge_base"
    / "performance_critical_params.json"
)


def _load_performance_critical_params() -> Dict:
    """Load the performance-critical parameters knowledge base."""
    try:
        with open(_KNOWLEDGE_BASE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _format_params_reference(params_data: Dict) -> str:
    """
    Format the performance-critical parameters as a reference table + full descriptions.

    Each parameter is shown with its name, type, default, valid range/values,
    and impact. Full descriptions are included without truncation.
    """
    parameters = params_data.get("parameters", {})
    if not parameters:
        return "## Available Parameters\n(knowledge base not available)"

    lines = [
        "## Available FastDDS Parameters",
        "Use ONLY these parameter names in the `\"set\"` object of your JSON response.",
        "Parameters in `\"delete\"` must also be from this list.",
        "",
        "| Parameter | Type | Default | Range / Values | Impact |",
        "|-----------|------|---------|----------------|--------|",
    ]

    for name, info in parameters.items():
        param_type = info.get("type", "")
        default = info.get("default", "")
        impact = info.get("impact", "")

        # Format range/values
        if "possible_values" in info:
            range_str = " | ".join(str(v) for v in info["possible_values"])
        elif "min" in info and "max" in info:
            unit = info.get("unit", "")
            range_str = f"{info['min']}–{info['max']} {unit}".strip()
        else:
            range_str = ""

        lines.append(f"| `{name}` | {param_type} | {default} | {range_str} | {impact} |")

    lines.append("")
    lines.append("**Parameter descriptions:**")
    for name, info in parameters.items():
        desc = info.get("description", "")
        # Full description — no truncation
        lines.append(f"- `{name}`: {desc}")

    return "\n".join(lines)


def _format_environment_section(env: EnvironmentInfo) -> str:
    """Format the environment information section of the prompt."""
    lines = [
        "## System Environment",
        f"- OS: {env.os_version}",
        f"- ROS2 Distribution: {env.ros2_distro}",
        f"- Active ROS2 Nodes ({len(env.active_nodes)}): {', '.join(env.active_nodes[:10]) or 'none'}",
    ]

    if env.active_topics:
        topic_strs = [f"{t.name} [{t.msg_type}]" for t in env.active_topics[:10]]
        lines.append(f"- Active ROS2 Topics ({len(env.active_topics)}): {', '.join(topic_strs)}")
    else:
        lines.append("- Active ROS2 Topics: none detected")

    if env.cpu_info:
        cpu = env.cpu_info
        freq_str = f" @ {cpu.frequency_mhz:.0f}MHz" if cpu.frequency_mhz else ""
        lines.append(f"- CPU: {cpu.model} ({cpu.cores_physical}P/{cpu.cores_logical}L cores{freq_str})")

    if env.memory_info:
        mem = env.memory_info
        lines.append(
            f"- Memory: {mem.total_mb:.0f}MB total, {mem.available_mb:.0f}MB available "
            f"({mem.used_percent:.1f}% used)"
        )

    return "\n".join(lines)


def _format_pipeline_topology_section(topology: Optional[PipelineTopology]) -> str:
    """
    Format the pipeline topology section of the prompt as a structured JSON object.

    The JSON is node-centric: for each pipeline node, lists the topics it publishes
    and subscribes to, together with message type, QoS, and average message size.
    A top-level "pipeline info" block summarises cross-process communication and
    node count so the LLM can select appropriate transport/intraprocess parameters.
    """
    if topology is None:
        return (
            "## Pipeline Topology\n"
            "Not available — pipeline topology could not be collected."
        )

    if not topology.nodes and not topology.topics:
        return (
            "## Pipeline Topology\n"
            "No active nodes or topics detected during benchmark."
        )

    # --- Determine cross-process flag ---
    cross_process: Optional[bool] = None
    if topology.process_groups:
        n_processes = len(topology.process_groups)
        # Count standalone nodes (pipeline nodes not in any container)
        all_components: set = set()
        for members in topology.process_groups.values():
            all_components.update(members)
        n_standalone = sum(1 for n in topology.nodes if n not in all_components)
        cross_process = (n_processes + n_standalone) > 1

    # --- Build per-node published/subscribed topic maps ---
    # node_full_path → {"published": [...], "subscribed": [...]}
    node_topics: Dict[str, Dict] = {n: {"published": [], "subscribed": []} for n in topology.nodes}

    for topic in topology.topics:
        topic_entry: Dict = {"topic name": topic.name, "topic type": topic.msg_type}
        if topic.qos_reliability:
            topic_entry["qos reliability"] = topic.qos_reliability
        if topic.msg_size_bytes is not None:
            topic_entry["avg msg size bytes"] = topic.msg_size_bytes

        for pub in topic.publishers:
            if pub in node_topics:
                node_topics[pub]["published"].append(topic_entry)

        sub_entry = dict(topic_entry)
        if topic.qos_durability:
            sub_entry["qos durability"] = topic.qos_durability
        for sub in topic.subscribers:
            if sub in node_topics:
                node_topics[sub]["subscribed"].append(sub_entry)

    # --- Assemble the output dict ---
    pipeline_info: Dict = {
        "number of ros2 nodes": len(topology.nodes),
    }
    if cross_process is not None:
        pipeline_info["cross process communication"] = cross_process

    nodes_info: Dict = {}
    for i, node_name in enumerate(topology.nodes, start=1):
        node_entry: Dict = {"node name": node_name}
        published = node_topics[node_name]["published"]
        subscribed = node_topics[node_name]["subscribed"]
        if published:
            node_entry["published topics"] = {
                f"topic {j}": t for j, t in enumerate(published, start=1)
            }
        if subscribed:
            node_entry["subscribed topics"] = {
                f"topic {j}": t for j, t in enumerate(subscribed, start=1)
            }
        nodes_info[f"node {i}"] = node_entry

    topology_dict: Dict = {
        "pipeline info": pipeline_info,
        "ros2 nodes info": nodes_info,
    }

    topology_json = json.dumps(topology_dict, indent=2)
    return f"## Pipeline Topology\n\n{topology_json}"


def _format_requirements_section(reqs: PerformanceRequirements) -> str:
    """Format the performance requirements section of the prompt."""
    lines = ["## Performance Requirements"]

    if reqs.latency:
        lat = reqs.latency
        req_str = "REQUIRED" if not lat.optional else "optional"
        targets = []
        if lat.target_mean_ms:
            targets.append(f"mean ≤ {lat.target_mean_ms}ms")
        if lat.target_p95_ms:
            targets.append(f"p95 ≤ {lat.target_p95_ms}ms")
        if lat.target_p99_ms:
            targets.append(f"p99 ≤ {lat.target_p99_ms}ms")
        lines.append(f"- Latency [{req_str}]: {', '.join(targets)}")

    if reqs.throughput:
        thr = reqs.throughput
        req_str = "REQUIRED" if not thr.optional else "optional"
        targets = []
        if thr.target_msgs_per_sec:
            targets.append(f"≥ {thr.target_msgs_per_sec} msgs/sec")
        if thr.target_mbps:
            targets.append(f"≥ {thr.target_mbps} Mbps")
        lines.append(f"- Throughput [{req_str}]: {', '.join(targets)}")

    if reqs.reliability:
        rel = reqs.reliability
        req_str = "REQUIRED" if not rel.optional else "optional"
        if rel.max_packet_loss_rate is not None:
            lines.append(
                f"- Reliability [{req_str}]: packet loss ≤ {rel.max_packet_loss_rate * 100:.3f}%"
            )

    if reqs.cpu_usage:
        cpu = reqs.cpu_usage
        req_str = "REQUIRED" if not cpu.optional else "optional"
        if cpu.max_percent:
            lines.append(f"- CPU Usage [{req_str}]: ≤ {cpu.max_percent}%")

    if reqs.memory_usage:
        mem = reqs.memory_usage
        req_str = "REQUIRED" if not mem.optional else "optional"
        if mem.max_mb:
            lines.append(f"- Memory Usage [{req_str}]: ≤ {mem.max_mb}MB")

    if len(lines) == 1:
        lines.append("- No specific performance requirements specified")

    return "\n".join(lines)


def _format_single_epoch_detail(it: OptimizationIteration, reqs: Optional[PerformanceRequirements] = None) -> str:
    """
    Format the full optimization detail for a single past epoch.

    Includes:
    - Benchmark results (all metrics)
    - Performance gaps (what was not met)
    - LLM reasoning / adjustment strategy
    - Parameters that were set and deleted
    - Whether the adjustment was effective (score change)
    """
    lines = [f"### Epoch {it.iteration_number} Detail"]

    # Benchmark results
    if it.results:
        r = it.results
        lines.append("**Benchmark Results:**")
        if r.mean_latency_ms is not None:
            lines.append(f"  - Mean Latency: {r.mean_latency_ms:.3f}ms")
        if r.p95_latency_ms is not None:
            lines.append(f"  - P95 Latency: {r.p95_latency_ms:.3f}ms")
        if r.p99_latency_ms is not None:
            lines.append(f"  - P99 Latency: {r.p99_latency_ms:.3f}ms")
        if r.msgs_per_sec is not None:
            lines.append(f"  - Throughput: {r.msgs_per_sec:.1f} msgs/sec")
        if r.packet_loss_rate is not None:
            lines.append(f"  - Packet Loss: {r.packet_loss_rate * 100:.4f}%")
        if r.cpu_percent is not None:
            lines.append(f"  - CPU Usage: {r.cpu_percent:.2f}%")
        if r.memory_mb is not None:
            lines.append(f"  - Memory: {r.memory_mb:.1f}MB")
    elif it.benchmark_error:
        lines.append(f"**Benchmark FAILED:** {it.benchmark_error}")

    # Outcome
    status = "✓ ALL REQUIRED MET" if it.required_metrics_met else "✗ REQUIRED NOT MET"
    lines.append(f"**Outcome:** score={it.performance_score:.3f} — {status}")

    # Adjustment strategy (LLM reasoning)
    if it.llm_reasoning and it.llm_reasoning != "[initial config provided by user]":
        lines.append(f"**Adjustment Strategy:** {it.llm_reasoning}")

    # Parameters applied
    if it.params_set:
        params_str = json.dumps(it.params_set, indent=4)
        lines.append(f"**Parameters Set:**\n```json\n{params_str}\n```")
    if it.params_deleted:
        lines.append(f"**Parameters Deleted (reverted to defaults):** {it.params_deleted}")

    return "\n".join(lines)


def _format_epoch_history(
    past_iterations: List[OptimizationIteration],
    reqs: Optional[PerformanceRequirements] = None,
) -> str:
    """
    Format the optimization history section of the prompt.

    Strategy:
    - Last 2 epochs: full details (results, gaps, strategy, params, effectiveness)
    - Older epochs: one-line summary only

    This gives the LLM a clear picture of recent optimization direction
    while keeping the prompt size bounded for older history.

    Args:
        past_iterations: List of completed OptimizationIteration objects,
                         ordered from oldest to newest.
        reqs: Performance requirements (for gap context).

    Returns:
        Formatted epoch history section, or empty string if no history.
    """
    if not past_iterations:
        return ""

    lines = ["## Optimization History"]

    # Split into older (summary only) and recent (full detail)
    if len(past_iterations) <= 2:
        older = []
        recent = past_iterations
    else:
        older = past_iterations[:-2]
        recent = past_iterations[-2:]

    # Older epochs: one-line summary
    if older:
        lines.append("### Earlier Epochs (summary)")
        for it in older:
            score = f"{it.performance_score:.3f}" if it.performance_score else "N/A"
            status = "✓ MET" if it.required_metrics_met else "✗ NOT MET"
            if it.results:
                r = it.results
                lat = f"{r.mean_latency_ms:.3f}ms" if r.mean_latency_ms is not None else "N/A"
                thr = f"{r.msgs_per_sec:.1f} msg/s" if r.msgs_per_sec is not None else "N/A"
                lines.append(
                    f"- Epoch {it.iteration_number}: score={score}, "
                    f"mean_latency={lat}, throughput={thr} — {status}"
                )
            elif it.benchmark_error:
                lines.append(
                    f"- Epoch {it.iteration_number}: BENCHMARK FAILED — {it.benchmark_error[:80]}"
                )
            else:
                lines.append(f"- Epoch {it.iteration_number}: score={score} — {status}")
        lines.append("")

    # Recent 2 epochs: full detail
    if recent:
        lines.append("### Recent Epochs (full detail)")
        for it in recent:
            lines.append(_format_single_epoch_detail(it, reqs))
            lines.append("")

    return "\n".join(lines)


def build_feedback_prompt(
    requirements: RequirementsConfig,
    env: EnvironmentInfo,
    current_config_params: Dict,
    results: Optional[BenchmarkResults],
    performance_gaps: Dict[str, str],
    iteration: int,
    past_iterations: Optional[List[OptimizationIteration]] = None,
    benchmark_error: Optional[str] = None,
    pipeline_topology: Optional[PipelineTopology] = None,
) -> str:
    """
    Build a feedback prompt for iterative optimization.

    This prompt is used when the previous configuration did not meet requirements,
    OR when the benchmark failed to run (results=None, benchmark_error set).

    Args:
        requirements: User requirements with performance targets.
        env: Environment information (collected at session start).
        current_config_params: Accumulated dict of parameter name → value from
                               all past LLM epochs. Shows the LLM what is currently set.
        results: Benchmark results from the last test run, or None if benchmark failed.
        performance_gaps: Dictionary of metric name → gap description.
        iteration: Current iteration number (for context).
        past_iterations: All completed iterations so far (for epoch history).
                         Should NOT include the current iteration being generated.
        benchmark_error: Error message if the benchmark failed to run (results=None).
        pipeline_topology: Live pipeline topology collected during the last benchmark run.

    Returns:
        Feedback prompt string to send to the LLM.
    """
    if benchmark_error:
        situation = (
            f"This is iteration {iteration} of the optimization loop. "
            f"The previous benchmark FAILED TO RUN with error: \"{benchmark_error}\". "
            "No performance data is available from the previous run. "
            "Your task is to suggest improved FastDDS parameter values that may work better."
        )
    else:
        situation = (
            f"This is iteration {iteration} of the optimization loop. "
            "The previous configuration did NOT fully meet the requirements. "
            "Your task is to generate improved FastDDS parameter values to close the performance gaps."
        )

    # Load performance-critical parameters reference
    params_data = _load_performance_critical_params()
    params_reference = _format_params_reference(params_data)

    system_context = f"""You are an expert in FastDDS (eProsima Fast DDS) configuration optimization for ROS2.

## ROS2 and DDS Background

**ROS2 Nodes:**
A ROS2 node is an independent executable (or composable component) that performs a discrete function. Nodes are the primary computational units. Each node has a unique name and optional namespace (e.g., `/publisher`, `/r2b/MonitorNode`). Nodes that run in the same OS process can share memory directly; nodes in different processes communicate over the network stack.

**Topics and Publish/Subscribe:**
Nodes exchange data through *topics* — named, typed communication channels. A *publisher* node writes messages to a topic; one or more *subscriber* nodes receive those messages asynchronously. The message type defines the schema (e.g., `std_msgs/msg/Header`). Topics are the primary data-flow primitive in ROS2.

**ROS2 and DDS:**
ROS2 uses DDS (Data Distribution Service) as its communication middleware. By default, ROS2 uses eProsima Fast DDS as the DDS implementation. Every topic publish/subscribe pair maps directly to a DDS DataWriter/DataReader pair. DDS governs:
- **Transport**: UDP unicast/multicast, shared memory (SHM), intra-process
- **QoS policies**: reliability (RELIABLE/BEST_EFFORT), durability, history depth, etc.
- **Discovery**: how nodes find each other at startup
- **Flow control**: buffer sizes, heartbeat periods, acknowledgment delays

FastDDS configuration therefore directly controls the end-to-end latency, throughput, and reliability of all ROS2 communication. Tuning FastDDS parameters is the correct lever for meeting the performance targets in this optimization loop.

---

{situation}

IMPORTANT INSTRUCTIONS:
1. Focus on the REQUIRED metrics that are not yet met
2. Consider parameter interactions (e.g., increasing buffer sizes may increase memory usage)
3. You MUST only use parameter names from the "Available FastDDS Parameters" table below
4. Start your response with a brief reasoning explanation (one paragraph)
5. Then output a structured JSON object with your parameter changes

PARAMETER OPERATION RULES:
- **Add or modify a parameter**: include it in the `"set"` object. You may ONLY use parameter
  names that exist in the "Available FastDDS Parameters" table (i.e., parameters present in
  `fastdds_config_template.xml`). Any unknown parameter name will be ignored.
- **Delete a parameter** (revert to system default): include its name in the `"delete"` list.
  This removes the parameter from the accumulated config, reverting it to the template default.
  Use this when a previously set parameter is causing problems or is no longer needed.

OUTPUT FORMAT:
First write a brief reasoning paragraph starting with "Reasoning:".
Then output a JSON object in a ```json ... ``` code block with this structure:

```json
{{
  "set": {{
    "param_name": value,
    ...
  }},
  "delete": ["param_name_to_revert", ...]
}}
```

Both `"set"` and `"delete"` are optional — omit either if not needed.

Example output:
Reasoning: The mean latency is 153ms vs target 100ms. I will reduce the heartbeat period
to speed up loss detection and lower response delays. I will also delete udp_send_buffer_size
since it was previously set too high and is increasing memory pressure without latency benefit.

```json
{{
  "set": {{
    "writer_heartbeat_period_nanosec": 50000000,
    "reader_heartbeat_response_delay_nanosec": 1000000,
    "writer_nack_response_delay_nanosec": 1000000
  }},
  "delete": ["udp_send_buffer_size"]
}}
```"""

    env_section = _format_environment_section(env)
    req_section = _format_requirements_section(requirements.performance_requirements)

    # Pipeline topology (collected during benchmark run)
    topology_section = _format_pipeline_topology_section(pipeline_topology)

    # Epoch history (last 2 epochs full detail, older as one-line summary)
    history_section = _format_epoch_history(
        past_iterations or [],
        reqs=requirements.performance_requirements,
    )

    # Format current results (or failure notice)
    if results is not None:
        results_lines = ["## Latest Benchmark Results"]
        if results.mean_latency_ms is not None:
            results_lines.append(f"- Mean Latency: {results.mean_latency_ms:.3f}ms")
        if results.p95_latency_ms is not None:
            results_lines.append(f"- P95 Latency: {results.p95_latency_ms:.3f}ms")
        if results.p99_latency_ms is not None:
            results_lines.append(f"- P99 Latency: {results.p99_latency_ms:.3f}ms")
        if results.msgs_per_sec is not None:
            results_lines.append(f"- Throughput: {results.msgs_per_sec:.1f} msgs/sec")
        if results.packet_loss_rate is not None:
            results_lines.append(f"- Packet Loss: {results.packet_loss_rate * 100:.4f}%")
        if results.cpu_percent is not None:
            results_lines.append(f"- CPU Usage: {results.cpu_percent:.2f}%")
        if results.memory_mb is not None:
            results_lines.append(f"- Memory Usage: {results.memory_mb:.1f}MB")
        results_section = "\n".join(results_lines)
    else:
        results_section = (
            "## Latest Benchmark Results\n"
            f"BENCHMARK FAILED: {benchmark_error or 'unknown error'}\n"
            "No performance metrics available."
        )

    # Format performance gaps
    gaps_lines = ["## Performance Gaps (what needs to improve)"]
    if performance_gaps:
        for metric, gap_desc in performance_gaps.items():
            gaps_lines.append(f"- {metric}: {gap_desc}")
    else:
        gaps_lines.append(
            "- No benchmark data available; suggest parameters targeting the requirements above."
        )
    gaps_section = "\n".join(gaps_lines)

    # Current accumulated parameter values
    if current_config_params:
        current_params_json = json.dumps(current_config_params, indent=2)
        current_config_section = (
            "## Current Accumulated Parameter Values\n"
            "These are the parameters currently set (accumulated from all past LLM epochs).\n"
            "```json\n"
            f"{current_params_json}\n"
            "```"
        )
    else:
        current_config_section = (
            "## Current Accumulated Parameter Values\n"
            "(No previous LLM parameters — this is the first LLM-generated epoch.\n"
            "The initial config was provided by the user.)"
        )

    # Build the full prompt
    sections = [
        system_context,
        "---",
        params_reference,
        "---",
        env_section,
        "---",
        topology_section,
        "---",
        req_section,
    ]

    if history_section:
        sections += ["---", history_section]

    sections += [
        "---",
        results_section,
        "---",
        gaps_section,
        "---",
        current_config_section,
        "---",
        "Based on the above context, generate improved FastDDS parameter values.\n"
        "Start with a \"Reasoning:\" paragraph explaining:\n"
        "  1. What the current performance gaps are\n"
        "  2. What you tried in previous epochs and whether it was effective\n"
        "  3. What you plan to change now and why\n"
        "Then provide the JSON object with `\"set\"` and/or `\"delete\"` keys.\n"
        "Only include parameters you want to change — the system fills in defaults for the rest.",
    ]

    return "\n\n".join(sections)
