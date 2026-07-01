# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Requirements Parser: reads and parses user_requirements.xml into typed Python models.

The XML file format is:
    <optimization_requirements>
        <benchmark>
            <test_file>/path/to/benchmark.py</test_file>
            <launch_command>launch_test</launch_command>
        </benchmark>
        <performance_requirements>
            <latency optional="false">
                <target_mean_ms>10</target_mean_ms>
                <target_p95_ms>15</target_p95_ms>
                <target_p99_ms>20</target_p99_ms>
            </latency>
            <throughput optional="true">
                <target_msgs_per_sec>1000</target_msgs_per_sec>
                <target_mbps>100</target_mbps>
            </throughput>
            <reliability optional="false">
                <max_packet_loss_rate>0.001</max_packet_loss_rate>
            </reliability>
            <cpu_usage optional="true">
                <max_percent>50</max_percent>
            </cpu_usage>
            <memory_usage optional="true">
                <max_mb>1024</max_mb>
            </memory_usage>
        </performance_requirements>
        <optimization_settings>
            <max_iterations>5</max_iterations>
            <convergence_threshold>0.05</convergence_threshold>
        </optimization_settings>
        <llm_config>
            <provider>openrouter</provider>
            <model>openrouter/free</model>
            <api_key_env>LLM_API_KEY</api_key_env>
        </llm_config>
    </optimization_requirements>
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from ..models import (
    BenchmarkConfig,
    CpuUsageRequirement,
    LatencyRequirement,
    LLMConfig,
    MemoryUsageRequirement,
    OptimizationSettings,
    PerformanceRequirements,
    ReliabilityRequirement,
    RequirementsConfig,
    ThroughputRequirement,
)


def _get_text(element: ET.Element, tag: str, default: Optional[str] = None) -> Optional[str]:
    """
    Safely extract text content from a child XML element.

    Args:
        element: Parent XML element to search within.
        tag: Tag name of the child element to find.
        default: Value to return if the child element is not found.

    Returns:
        Text content of the child element, or default if not found.
    """
    child = element.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return default


def _get_float(element: ET.Element, tag: str, default: Optional[float] = None) -> Optional[float]:
    """
    Safely extract a float value from a child XML element.

    Args:
        element: Parent XML element to search within.
        tag: Tag name of the child element to find.
        default: Value to return if the child element is not found or invalid.

    Returns:
        Float value of the child element, or default if not found/invalid.
    """
    text = _get_text(element, tag)
    if text is not None:
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"Expected a numeric value for <{tag}>, got '{text}'")
    return default


def _get_int(element: ET.Element, tag: str, default: Optional[int] = None) -> Optional[int]:
    """
    Safely extract an integer value from a child XML element.

    Args:
        element: Parent XML element to search within.
        tag: Tag name of the child element to find.
        default: Value to return if the child element is not found or invalid.

    Returns:
        Integer value of the child element, or default if not found/invalid.
    """
    text = _get_text(element, tag)
    if text is not None:
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"Expected an integer value for <{tag}>, got '{text}'")
    return default


def _get_optional_flag(element: ET.Element) -> bool:
    """
    Extract the 'optional' attribute from an XML element.

    The 'optional' attribute controls whether a performance requirement is
    mandatory (optional="false") or a nice-to-have (optional="true").

    Args:
        element: XML element with an optional 'optional' attribute.

    Returns:
        True if optional="true", False otherwise (default is False = required).
    """
    optional_str = element.get("optional", "false").lower().strip()
    return optional_str in ("true", "1", "yes")


def _parse_benchmark(root: ET.Element, xml_dir: Path) -> BenchmarkConfig:
    """
    Parse the <benchmark> section of the requirements XML.

    Relative <test_file> paths are resolved relative to the directory that
    contains the requirements XML file (xml_dir), so users can write:
        <test_file>src/pipeline_launch/benchmark/inter_process_benchmark.py</test_file>
    and it will be resolved correctly regardless of the working directory.

    Args:
        root: Root XML element of the requirements file.
        xml_dir: Directory containing the requirements XML file.

    Returns:
        BenchmarkConfig with test_file and launch_command.

    Raises:
        ValueError: If the <benchmark> section is missing or test_file is not specified.
    """
    benchmark_elem = root.find("benchmark")
    if benchmark_elem is None:
        raise ValueError("Missing required <benchmark> section in requirements XML")

    test_file = _get_text(benchmark_elem, "test_file")
    if not test_file:
        raise ValueError("Missing required <test_file> in <benchmark> section")

    # Resolve relative paths relative to the XML file's directory
    test_file_path = Path(test_file)
    if not test_file_path.is_absolute():
        test_file_path = (xml_dir / test_file_path).resolve()
    test_file = str(test_file_path)

    launch_command = _get_text(benchmark_elem, "launch_command", default="launch_test")

    return BenchmarkConfig(
        test_file=test_file,
        launch_command=launch_command,
    )


def _parse_performance_requirements(root: ET.Element) -> PerformanceRequirements:
    """
    Parse the <performance_requirements> section of the requirements XML.

    Each sub-element (latency, throughput, etc.) has an 'optional' attribute
    that determines whether it is a hard requirement or a nice-to-have.

    Args:
        root: Root XML element of the requirements file.

    Returns:
        PerformanceRequirements with all parsed sub-requirements.
    """
    perf_elem = root.find("performance_requirements")
    if perf_elem is None:
        # Performance requirements section is optional in the XML
        return PerformanceRequirements()

    # --- Latency ---
    latency = None
    latency_elem = perf_elem.find("latency")
    if latency_elem is not None:
        latency = LatencyRequirement(
            optional=_get_optional_flag(latency_elem),
            target_mean_ms=_get_float(latency_elem, "target_mean_ms"),
            target_p95_ms=_get_float(latency_elem, "target_p95_ms"),
            target_p99_ms=_get_float(latency_elem, "target_p99_ms"),
        )

    # --- Throughput ---
    throughput = None
    throughput_elem = perf_elem.find("throughput")
    if throughput_elem is not None:
        throughput = ThroughputRequirement(
            optional=_get_optional_flag(throughput_elem),
            target_msgs_per_sec=_get_float(throughput_elem, "target_msgs_per_sec"),
            target_mbps=_get_float(throughput_elem, "target_mbps"),
        )

    # --- Reliability ---
    reliability = None
    reliability_elem = perf_elem.find("reliability")
    if reliability_elem is not None:
        reliability = ReliabilityRequirement(
            optional=_get_optional_flag(reliability_elem),
            max_packet_loss_rate=_get_float(reliability_elem, "max_packet_loss_rate"),
        )

    # --- CPU Usage (accepts both <cpu_max_usage> and legacy <cpu_usage>) ---
    cpu_usage = None
    cpu_elem = perf_elem.find("cpu_max_usage") or perf_elem.find("cpu_usage")
    if cpu_elem is not None:
        cpu_usage = CpuUsageRequirement(
            optional=_get_optional_flag(cpu_elem),
            max_percent=_get_float(cpu_elem, "max_percent"),
        )

    # --- Memory Usage (accepts both <memory_max_usage> and legacy <memory_usage>) ---
    memory_usage = None
    mem_elem = perf_elem.find("memory_max_usage") or perf_elem.find("memory_usage")
    if mem_elem is not None:
        memory_usage = MemoryUsageRequirement(
            optional=_get_optional_flag(mem_elem),
            max_mb=_get_float(mem_elem, "max_mb"),
        )

    return PerformanceRequirements(
        latency=latency,
        throughput=throughput,
        reliability=reliability,
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
    )


def _parse_optimization_settings(root: ET.Element) -> OptimizationSettings:
    """
    Parse the <optimization_settings> section of the requirements XML.

    Args:
        root: Root XML element of the requirements file.

    Returns:
        OptimizationSettings with max_iterations and convergence_threshold.
    """
    settings_elem = root.find("optimization_settings")
    if settings_elem is None:
        # Use defaults if section is missing
        return OptimizationSettings()

    max_iterations = _get_int(settings_elem, "max_iterations", default=5)
    convergence_threshold = _get_float(settings_elem, "convergence_threshold", default=0.05)

    return OptimizationSettings(
        max_iterations=max_iterations,
        convergence_threshold=convergence_threshold,
    )


def _parse_llm_config(root: ET.Element) -> LLMConfig:
    """
    Parse the <llm_config> section of the requirements XML.

    Args:
        root: Root XML element of the requirements file.

    Returns:
        LLMConfig with provider, model, base_url, and api_key_env.

    Raises:
        ValueError: If the <llm_config> section is missing.
    """
    llm_elem = root.find("llm_config")
    if llm_elem is None:
        raise ValueError("Missing required <llm_config> section in requirements XML")

    provider = _get_text(llm_elem, "provider", default="openrouter")
    model = _get_text(llm_elem, "model", default="openrouter/free")
    base_url = _get_text(llm_elem, "base_url", default=None)
    api_key_env = _get_text(llm_elem, "api_key_env", default="LLM_API_KEY")
    plugin_module = _get_text(llm_elem, "plugin_module", default=None)

    # If plugin_module is specified, default provider to "plugin"
    if plugin_module and provider == "openai":
        provider = "plugin"

    return LLMConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        plugin_module=plugin_module,
    )


def parse_requirements(xml_path: str) -> RequirementsConfig:
    """
    Parse a user_requirements.xml file into a RequirementsConfig model.

    This is the main entry point for the requirements parser. It reads the XML
    file, validates its structure, and returns a fully typed Python model.

    Args:
        xml_path: Path to the user_requirements.xml file.

    Returns:
        RequirementsConfig containing all parsed requirements.

    Raises:
        FileNotFoundError: If the XML file does not exist.
        ValueError: If the XML is malformed or missing required sections.
        ET.ParseError: If the XML is not valid XML syntax.

    Example:
        >>> config = parse_requirements("user_requirements.xml")
        >>> print(config.benchmark.test_file)
        '/path/to/benchmark.py'
        >>> print(config.llm_config.model)
        'gpt-4'
    """
    path = Path(xml_path)
    if not path.exists():
        raise FileNotFoundError(f"Requirements file not found: {xml_path}")
    if not path.is_file():
        raise ValueError(f"Requirements path is not a file: {xml_path}")

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse XML file '{xml_path}': {e}") from e

    root = tree.getroot()

    # Validate root element
    if root.tag != "optimization_requirements":
        raise ValueError(
            f"Expected root element <optimization_requirements>, got <{root.tag}>"
        )

    # Directory containing the XML file — used to resolve relative test_file paths
    xml_dir = path.resolve().parent

    # Parse each section
    benchmark = _parse_benchmark(root, xml_dir)
    performance_requirements = _parse_performance_requirements(root)
    optimization_settings = _parse_optimization_settings(root)
    llm_config = _parse_llm_config(root)

    return RequirementsConfig(
        benchmark=benchmark,
        performance_requirements=performance_requirements,
        optimization_settings=optimization_settings,
        llm_config=llm_config,
    )
