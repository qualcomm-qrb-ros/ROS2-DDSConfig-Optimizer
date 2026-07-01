# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Unit tests for the config writing behavior.

Since config generation is now done by the LLM (which outputs complete XML),
these tests verify that DDSParameterSet.xml_content is correctly written to
a file path — the pattern used in optimization_loop.py.
"""

import pytest
from pathlib import Path

from dds_optimizer.models import DDSParameterSet

# Sample FastDDS XML configs for testing
SAMPLE_XML_PROFILES = """<?xml version="1.0" encoding="UTF-8"?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor>
      <transport_id>udp_transport</transport_id>
      <type>UDPv4</type>
      <sendBufferSize>524288</sendBufferSize>
      <receiveBufferSize>524288</receiveBufferSize>
    </transport_descriptor>
  </transport_descriptors>
  <participant profile_name="default_profile" is_default_profile="true">
    <rtps>
      <useBuiltinTransports>true</useBuiltinTransports>
    </rtps>
  </participant>
  <data_writer profile_name="default_writer">
    <historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy>
    <qos>
      <reliability>
        <kind>RELIABLE</kind>
      </reliability>
    </qos>
  </data_writer>
  <data_reader profile_name="default_reader">
    <historyMemoryPolicy>PREALLOCATED_WITH_REALLOC</historyMemoryPolicy>
    <qos>
      <reliability>
        <kind>RELIABLE</kind>
      </reliability>
    </qos>
  </data_reader>
</profiles>"""

SAMPLE_XML_DDS = """<?xml version="1.0"?>
<dds>
  <profiles>
    <participant profile_name="default">
      <rtps>
        <useBuiltinTransports>true</useBuiltinTransports>
      </rtps>
    </participant>
  </profiles>
</dds>"""


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def profiles_param_set():
    """DDSParameterSet with <profiles> root XML."""
    return DDSParameterSet(
        xml_content=SAMPLE_XML_PROFILES,
        reasoning="Test configuration with profiles root",
    )


@pytest.fixture
def dds_param_set():
    """DDSParameterSet with <dds> root XML."""
    return DDSParameterSet(
        xml_content=SAMPLE_XML_DDS,
        reasoning="Test configuration with dds root",
    )


# -----------------------------------------------------------------------
# DDSParameterSet model tests
# -----------------------------------------------------------------------

def test_dds_parameter_set_has_xml_content():
    """Test that DDSParameterSet stores xml_content."""
    ps = DDSParameterSet(xml_content=SAMPLE_XML_PROFILES, reasoning="test")
    assert ps.xml_content == SAMPLE_XML_PROFILES
    assert ps.reasoning == "test"


def test_dds_parameter_set_default_xml_content():
    """Test that DDSParameterSet defaults xml_content to empty string."""
    ps = DDSParameterSet()
    assert ps.xml_content == ""
    assert ps.reasoning is None


def test_dds_parameter_set_no_parameters_field():
    """Test that DDSParameterSet has a 'parameters' dict field (JSON-params flow)."""
    ps = DDSParameterSet(parameters={"history_depth": 5})
    assert hasattr(ps, "parameters")
    assert ps.parameters == {"history_depth": 5}


# -----------------------------------------------------------------------
# XML write-to-file tests (simulating optimization_loop.py behavior)
# -----------------------------------------------------------------------

def test_write_xml_content_to_file(tmp_path, profiles_param_set):
    """Test that xml_content can be written directly to a file."""
    output_path = tmp_path / "fastdds_config.xml"
    output_path.write_text(profiles_param_set.xml_content)
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_written_xml_is_readable(tmp_path, profiles_param_set):
    """Test that the written XML file is readable and contains expected content."""
    output_path = tmp_path / "fastdds_config.xml"
    output_path.write_text(profiles_param_set.xml_content)
    content = output_path.read_text()
    assert "profiles" in content
    assert "participant" in content


def test_written_xml_has_declaration(tmp_path, profiles_param_set):
    """Test that the written XML file has an XML declaration."""
    output_path = tmp_path / "fastdds_config.xml"
    output_path.write_text(profiles_param_set.xml_content)
    content = output_path.read_text()
    assert content.startswith("<?xml")


def test_written_xml_has_transport_descriptors(tmp_path, profiles_param_set):
    """Test that the written XML contains transport_descriptors."""
    output_path = tmp_path / "fastdds_config.xml"
    output_path.write_text(profiles_param_set.xml_content)
    content = output_path.read_text()
    assert "transport_descriptors" in content
    assert "UDPv4" in content


def test_written_xml_has_writer_reader(tmp_path, profiles_param_set):
    """Test that the written XML contains data_writer and data_reader profiles."""
    output_path = tmp_path / "fastdds_config.xml"
    output_path.write_text(profiles_param_set.xml_content)
    content = output_path.read_text()
    assert "data_writer" in content
    assert "data_reader" in content


def test_write_dds_root_xml(tmp_path, dds_param_set):
    """Test writing XML with <dds> root element."""
    output_path = tmp_path / "fastdds_config.xml"
    output_path.write_text(dds_param_set.xml_content)
    content = output_path.read_text()
    assert "<dds>" in content
    assert "participant" in content


def test_write_creates_parent_dirs(tmp_path, profiles_param_set):
    """Test that parent directories can be created before writing."""
    output_path = tmp_path / "subdir" / "nested" / "config.xml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(profiles_param_set.xml_content)
    assert output_path.exists()


def test_write_xml_content_roundtrip(tmp_path):
    """Test that xml_content survives a write-read roundtrip unchanged."""
    ps = DDSParameterSet(xml_content=SAMPLE_XML_PROFILES, reasoning="roundtrip test")
    output_path = tmp_path / "config.xml"
    output_path.write_text(ps.xml_content)
    read_back = output_path.read_text()
    assert read_back == SAMPLE_XML_PROFILES


def test_write_xml_with_reliability_settings(tmp_path):
    """Test writing XML that contains QoS reliability settings."""
    output_path = tmp_path / "config.xml"
    output_path.write_text(SAMPLE_XML_PROFILES)
    content = output_path.read_text()
    assert "RELIABLE" in content


def test_write_xml_with_buffer_sizes(tmp_path):
    """Test writing XML that contains buffer size settings."""
    output_path = tmp_path / "config.xml"
    output_path.write_text(SAMPLE_XML_PROFILES)
    content = output_path.read_text()
    assert "sendBufferSize" in content
    assert "receiveBufferSize" in content


def test_write_empty_xml_content(tmp_path):
    """Test that empty xml_content can be written (edge case)."""
    ps = DDSParameterSet(xml_content="", reasoning="empty")
    output_path = tmp_path / "empty.xml"
    output_path.write_text(ps.xml_content)
    assert output_path.exists()
    assert output_path.read_text() == ""
