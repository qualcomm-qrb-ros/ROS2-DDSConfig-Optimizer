# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for the requirements parser."""

import tempfile
from pathlib import Path

import pytest

from dds_optimizer.requirements.parser import parse_requirements


SAMPLE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<optimization_requirements>
    <benchmark>
        <test_file>/tmp/benchmark.py</test_file>
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
        </throughput>
        <reliability optional="false">
            <max_packet_loss_rate>0.001</max_packet_loss_rate>
        </reliability>
        <cpu_usage optional="true">
            <max_percent>50</max_percent>
        </cpu_usage>
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


@pytest.fixture
def sample_xml_file(tmp_path):
    """Create a temporary requirements XML file."""
    xml_file = tmp_path / "requirements.xml"
    xml_file.write_text(SAMPLE_XML)
    return str(xml_file)


def test_parse_benchmark(sample_xml_file):
    """Test that benchmark config is parsed correctly."""
    config = parse_requirements(sample_xml_file)
    assert config.benchmark.test_file == "/tmp/benchmark.py"
    assert config.benchmark.launch_command == "launch_test"


def test_parse_latency_requirements(sample_xml_file):
    """Test that latency requirements are parsed correctly."""
    config = parse_requirements(sample_xml_file)
    lat = config.performance_requirements.latency
    assert lat is not None
    assert lat.target_mean_ms == 10.0
    assert lat.target_p95_ms == 15.0
    assert lat.target_p99_ms == 20.0
    assert lat.optional is False


def test_parse_throughput_optional(sample_xml_file):
    """Test that optional throughput requirements are parsed correctly."""
    config = parse_requirements(sample_xml_file)
    thr = config.performance_requirements.throughput
    assert thr is not None
    assert thr.target_msgs_per_sec == 1000.0
    assert thr.optional is True


def test_parse_reliability_requirements(sample_xml_file):
    """Test that reliability requirements are parsed correctly."""
    config = parse_requirements(sample_xml_file)
    rel = config.performance_requirements.reliability
    assert rel is not None
    assert rel.max_packet_loss_rate == 0.001
    assert rel.optional is False


def test_parse_cpu_usage_optional(sample_xml_file):
    """Test that optional CPU usage requirements are parsed correctly."""
    config = parse_requirements(sample_xml_file)
    cpu = config.performance_requirements.cpu_usage
    assert cpu is not None
    assert cpu.max_percent == 50.0
    assert cpu.optional is True


def test_parse_optimization_settings(sample_xml_file):
    """Test that optimization settings are parsed correctly."""
    config = parse_requirements(sample_xml_file)
    settings = config.optimization_settings
    assert settings.max_iterations == 5
    assert settings.convergence_threshold == 0.05


def test_parse_llm_config(sample_xml_file):
    """Test that LLM configuration is parsed correctly."""
    config = parse_requirements(sample_xml_file)
    llm = config.llm_config
    assert llm.provider == "openrouter"
    assert llm.model == "openrouter/free"
    assert llm.base_url is None
    assert llm.api_key_env == "LLM_API_KEY"


def test_parse_missing_file():
    """Test that FileNotFoundError is raised for missing files."""
    with pytest.raises(FileNotFoundError):
        parse_requirements("/nonexistent/path/requirements.xml")


def test_parse_invalid_xml(tmp_path):
    """Test that ValueError is raised for invalid XML."""
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("this is not xml <><>")
    with pytest.raises(ValueError):
        parse_requirements(str(bad_xml))


def test_parse_minimal_xml(tmp_path):
    """Test parsing with only required fields."""
    minimal_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<optimization_requirements>
    <benchmark>
        <test_file>/tmp/bench.py</test_file>
        <launch_command>launch_test</launch_command>
    </benchmark>
    <performance_requirements>
        <latency optional="false">
            <target_mean_ms>5</target_mean_ms>
        </latency>
    </performance_requirements>
    <optimization_settings>
        <max_iterations>3</max_iterations>
        <convergence_threshold>0.1</convergence_threshold>
    </optimization_settings>
    <llm_config>
        <provider>openrouter</provider>
        <model>openrouter/free</model>
        <api_key_env>LLM_API_KEY</api_key_env>
    </llm_config>
</optimization_requirements>
"""
    xml_file = tmp_path / "minimal.xml"
    xml_file.write_text(minimal_xml)
    config = parse_requirements(str(xml_file))

    assert config.benchmark.test_file == "/tmp/bench.py"
    assert config.performance_requirements.latency.target_mean_ms == 5.0
    assert config.performance_requirements.throughput is None
    assert config.performance_requirements.reliability is None


def test_parse_openai_config(tmp_path):
    """Test parsing an OpenAI provider config with explicit base_url."""
    openai_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<optimization_requirements>
    <benchmark>
        <test_file>/tmp/bench.py</test_file>
        <launch_command>launch_test</launch_command>
    </benchmark>
    <performance_requirements>
        <latency optional="false">
            <target_mean_ms>10</target_mean_ms>
        </latency>
    </performance_requirements>
    <optimization_settings>
        <max_iterations>3</max_iterations>
        <convergence_threshold>0.1</convergence_threshold>
    </optimization_settings>
    <llm_config>
        <provider>openai</provider>
        <model>gpt-4o</model>
        <base_url>https://api.openai.com/v1</base_url>
        <api_key_env>LLM_API_KEY</api_key_env>
    </llm_config>
</optimization_requirements>
"""
    xml_file = tmp_path / "openai.xml"
    xml_file.write_text(openai_xml)
    config = parse_requirements(str(xml_file))

    llm = config.llm_config
    assert llm.provider == "openai"
    assert llm.model == "gpt-4o"
    assert llm.base_url == "https://api.openai.com/v1"
    assert llm.api_key_env == "LLM_API_KEY"


def test_parse_openrouter_no_base_url(tmp_path):
    """Test that OpenRouter config works without specifying base_url (auto-resolved)."""
    openrouter_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<optimization_requirements>
    <benchmark>
        <test_file>/tmp/bench.py</test_file>
        <launch_command>launch_test</launch_command>
    </benchmark>
    <performance_requirements>
        <latency optional="false">
            <target_mean_ms>10</target_mean_ms>
        </latency>
    </performance_requirements>
    <optimization_settings>
        <max_iterations>3</max_iterations>
        <convergence_threshold>0.1</convergence_threshold>
    </optimization_settings>
    <llm_config>
        <provider>openrouter</provider>
        <model>openrouter/free</model>
        <api_key_env>LLM_API_KEY</api_key_env>
    </llm_config>
</optimization_requirements>
"""
    xml_file = tmp_path / "openrouter.xml"
    xml_file.write_text(openrouter_xml)
    config = parse_requirements(str(xml_file))

    llm = config.llm_config
    assert llm.provider == "openrouter"
    assert llm.model == "openrouter/free"
    assert llm.base_url is None   # auto-resolved to https://openrouter.ai/api/v1 at call time
    assert llm.api_key_env == "LLM_API_KEY"


def test_dds_implementation_defaults_to_fastdds(tmp_path):
    xml = tmp_path / "req.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<optimization_requirements>'
        '<benchmark><test_file>/tmp/b.py</test_file></benchmark>'
        '<performance_requirements>'
        '<latency optional="false"><target_mean_ms>10</target_mean_ms></latency>'
        '</performance_requirements>'
        '<llm_config><provider>openrouter</provider><model>m</model>'
        '<api_key_env>LLM_API_KEY</api_key_env></llm_config>'
        '</optimization_requirements>'
    )
    from dds_optimizer.requirements.parser import parse_requirements
    cfg = parse_requirements(str(xml))
    assert cfg.dds_implementation == "fastdds"


def test_dds_implementation_parsed_cyclonedds(tmp_path):
    xml = tmp_path / "req.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<optimization_requirements>'
        '<dds_implementation>cyclonedds</dds_implementation>'
        '<benchmark><test_file>/tmp/b.py</test_file></benchmark>'
        '<performance_requirements>'
        '<latency optional="false"><target_mean_ms>10</target_mean_ms></latency>'
        '</performance_requirements>'
        '<llm_config><provider>openrouter</provider><model>m</model>'
        '<api_key_env>LLM_API_KEY</api_key_env></llm_config>'
        '</optimization_requirements>'
    )
    from dds_optimizer.requirements.parser import parse_requirements
    cfg = parse_requirements(str(xml))
    assert cfg.dds_implementation == "cyclonedds"


def test_invalid_dds_implementation_raises(tmp_path):
    xml = tmp_path / "req.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<optimization_requirements>'
        '<dds_implementation>nosuchdds</dds_implementation>'
        '<benchmark><test_file>/tmp/b.py</test_file></benchmark>'
        '<performance_requirements>'
        '<latency optional="false"><target_mean_ms>10</target_mean_ms></latency>'
        '</performance_requirements>'
        '<llm_config><provider>openrouter</provider><model>m</model>'
        '<api_key_env>LLM_API_KEY</api_key_env></llm_config>'
        '</optimization_requirements>'
    )
    from dds_optimizer.requirements.parser import parse_requirements
    import pytest
    with pytest.raises(ValueError):
        parse_requirements(str(xml))
