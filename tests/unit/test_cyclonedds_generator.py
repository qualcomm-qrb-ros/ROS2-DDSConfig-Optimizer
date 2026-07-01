# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the generic xml_path-driven CycloneDDS config generator."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dds_optimizer.backends.cyclonedds.generator import generate_cyclonedds_config

# Minimal KB stub covering element paths, a shared parent, and @attr paths.
KB = {
    "parameters": {
        "ack_delay": {"xml_path": "CycloneDDS/Domain/Internal/AckDelay"},
        "nack_delay": {"xml_path": "CycloneDDS/Domain/Internal/NackDelay"},
        "max_message_size": {"xml_path": "CycloneDDS/Domain/General/MaxMessageSize"},
        "socket_receive_buffer_size": {
            "xml_path": "CycloneDDS/Domain/Internal/SocketReceiveBufferSize/@min"
        },
    }
}

NS = "{https://cdds.io/config}"


def _generate(params: dict, tmp_path: Path) -> ET.Element:
    out = tmp_path / "cyclonedds.xml"
    generate_cyclonedds_config(params, KB, out)
    return ET.parse(out).getroot()


def test_root_and_domain(tmp_path):
    root = _generate({"ack_delay": "10 ms"}, tmp_path)
    assert root.tag == f"{NS}CycloneDDS"
    domain = root.find(f"{NS}Domain")
    assert domain is not None
    assert domain.get("Id") == "any"


def test_element_text_is_set_verbatim(tmp_path):
    root = _generate({"max_message_size": "65500B"}, tmp_path)
    el = root.find(f"{NS}Domain/{NS}General/{NS}MaxMessageSize")
    assert el is not None
    assert el.text == "65500B"


def test_attribute_path_sets_attribute_not_text(tmp_path):
    root = _generate({"socket_receive_buffer_size": "8 MiB"}, tmp_path)
    el = root.find(f"{NS}Domain/{NS}Internal/{NS}SocketReceiveBufferSize")
    assert el is not None
    assert el.get("min") == "8 MiB"
    assert (el.text or "").strip() == ""


def test_parent_nodes_are_shared(tmp_path):
    root = _generate({"ack_delay": "5 ms", "nack_delay": "50 ms"}, tmp_path)
    internals = root.findall(f"{NS}Domain/{NS}Internal")
    assert len(internals) == 1  # AckDelay and NackDelay share one <Internal>
    assert internals[0].find(f"{NS}AckDelay").text == "5 ms"
    assert internals[0].find(f"{NS}NackDelay").text == "50 ms"


def test_sparse_output_only_set_params_appear(tmp_path):
    root = _generate({"ack_delay": "10 ms"}, tmp_path)
    # No General branch when no General param was set.
    assert root.find(f"{NS}Domain/{NS}General") is None
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}NackDelay") is None


def test_unknown_param_is_ignored(tmp_path):
    # A param not in the KB is skipped rather than raising.
    root = _generate({"ack_delay": "10 ms", "not_a_real_param": 1}, tmp_path)
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}AckDelay").text == "10 ms"


def test_output_is_wellformed_xml_with_declaration(tmp_path):
    out = tmp_path / "c.xml"
    generate_cyclonedds_config({"ack_delay": "10 ms"}, KB, out)
    content = out.read_text()
    assert content.startswith("<?xml")
