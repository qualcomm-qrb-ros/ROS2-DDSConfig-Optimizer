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

# KB stub with type/min/max metadata for value-validation tests.
KB_TYPED = {
    "parameters": {
        "multiple_receive_threads": {
            "xml_path": "CycloneDDS/Domain/Internal/MultipleReceiveThreads",
            "type": "bool",
        },
        "delivery_queue_max_samples": {
            "xml_path": "CycloneDDS/Domain/Internal/DeliveryQueueMaxSamples",
            "type": "int",
            "min": 1,
            "max": 1000,
        },
        "ack_delay": {
            "xml_path": "CycloneDDS/Domain/Internal/AckDelay",
            "type": "string",
        },
    }
}

NS = "{https://cdds.io/config}"


def _generate(params: dict, tmp_path: Path) -> ET.Element:
    out = tmp_path / "cyclonedds.xml"
    generate_cyclonedds_config(params, KB, out)
    return ET.parse(out).getroot()


def _generate_kb(params: dict, kb: dict, tmp_path: Path) -> ET.Element:
    out = tmp_path / "cyclonedds.xml"
    generate_cyclonedds_config(params, kb, out)
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


# ---------------------------------------------------------------------------
# Value validation (skip semantically-invalid LLM values instead of writing
# them and having CycloneDDS reject the whole config).
# ---------------------------------------------------------------------------

def test_invalid_bool_value_is_skipped(tmp_path):
    # "A" is not a valid bool → the param is skipped, not written.
    root = _generate_kb({"multiple_receive_threads": "A"}, KB_TYPED, tmp_path)
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}MultipleReceiveThreads") is None


def test_valid_bool_value_is_written(tmp_path):
    root = _generate_kb({"multiple_receive_threads": "true"}, KB_TYPED, tmp_path)
    el = root.find(f"{NS}Domain/{NS}Internal/{NS}MultipleReceiveThreads")
    assert el is not None and el.text == "true"


def test_python_bool_value_is_written_lowercased(tmp_path):
    root = _generate_kb({"multiple_receive_threads": False}, KB_TYPED, tmp_path)
    el = root.find(f"{NS}Domain/{NS}Internal/{NS}MultipleReceiveThreads")
    assert el is not None and el.text == "false"


def test_int_out_of_range_is_skipped(tmp_path):
    # max is 1000 → 99999 is out of range and skipped.
    root = _generate_kb({"delivery_queue_max_samples": 99999}, KB_TYPED, tmp_path)
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}DeliveryQueueMaxSamples") is None


def test_non_numeric_int_is_skipped(tmp_path):
    root = _generate_kb({"delivery_queue_max_samples": "not_a_number"}, KB_TYPED, tmp_path)
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}DeliveryQueueMaxSamples") is None


def test_valid_int_in_range_is_written(tmp_path):
    root = _generate_kb({"delivery_queue_max_samples": 256}, KB_TYPED, tmp_path)
    el = root.find(f"{NS}Domain/{NS}Internal/{NS}DeliveryQueueMaxSamples")
    assert el is not None and el.text == "256"


def test_string_type_passes_through_unchecked(tmp_path):
    # string params accept unit-suffixed values verbatim (no validation).
    root = _generate_kb({"ack_delay": "12 ms"}, KB_TYPED, tmp_path)
    el = root.find(f"{NS}Domain/{NS}Internal/{NS}AckDelay")
    assert el is not None and el.text == "12 ms"


def test_invalid_value_does_not_block_other_params(tmp_path):
    # One invalid value is skipped; the other valid param is still written.
    root = _generate_kb(
        {"multiple_receive_threads": "A", "ack_delay": "3 ms"}, KB_TYPED, tmp_path
    )
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}MultipleReceiveThreads") is None
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}AckDelay").text == "3 ms"
