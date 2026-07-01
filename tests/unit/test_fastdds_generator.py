# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for FastDDS XML config generation via generator.py."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dds_optimizer.config.generator import generate_fastdds_config
from dds_optimizer.models import DDSParameterSet


def _generate(params: dict, tmp_path: Path) -> ET.Element:
    """Helper: generate XML and return the root element."""
    param_set = DDSParameterSet(parameters=params)
    out = tmp_path / "fastdds.xml"
    generate_fastdds_config(param_set, out)
    tree = ET.parse(out)
    return tree.getroot()


def _shm_td(root: ET.Element) -> ET.Element:
    """Find the SHM transport descriptor in the generated XML."""
    for td in root.iter("transport_descriptor"):
        if td.findtext("type") == "SHM":
            return td
    raise AssertionError("SHM transport_descriptor not found in generated XML")


class TestShmConstraintEnforcement:
    """
    FastDDS requires shm_segment_size >= shm_max_message_size.
    The generator must enforce this regardless of what the LLM sets.
    """

    def test_valid_shm_params_unchanged(self, tmp_path):
        """When segment_size >= max_message_size, values are written as-is."""
        root = _generate(
            {"shm_max_message_size": 131072, "shm_segment_size": 1048576},
            tmp_path,
        )
        td = _shm_td(root)
        assert td.findtext("maxMessageSize") == "131072"
        assert td.findtext("segment_size") == "1048576"

    def test_inverted_defaults_are_corrected(self, tmp_path):
        """
        Generator defaults (max=524288, seg=262144) are inverted — segment < max.
        When neither param is set by the LLM the generator must still produce a
        valid config where segment_size >= maxMessageSize.
        """
        root = _generate({}, tmp_path)
        td = _shm_td(root)
        max_msg = int(td.findtext("maxMessageSize"))
        seg = int(td.findtext("segment_size"))
        assert seg >= max_msg, (
            f"segment_size ({seg}) must be >= maxMessageSize ({max_msg})"
        )

    def test_llm_sets_segment_smaller_than_max(self, tmp_path):
        """LLM sets segment_size < max_message_size — generator corrects it."""
        root = _generate(
            {"shm_max_message_size": 524288, "shm_segment_size": 65536},
            tmp_path,
        )
        td = _shm_td(root)
        max_msg = int(td.findtext("maxMessageSize"))
        seg = int(td.findtext("segment_size"))
        assert seg >= max_msg, f"segment_size ({seg}) should have been corrected to >= {max_msg}"
        # Correction should be 4x the max message size
        assert seg == max_msg * 4

    def test_equal_values_are_valid(self, tmp_path):
        """segment_size == max_message_size is borderline-valid; should not be corrected."""
        size = 262144
        root = _generate(
            {"shm_max_message_size": size, "shm_segment_size": size},
            tmp_path,
        )
        td = _shm_td(root)
        assert int(td.findtext("maxMessageSize")) == size
        assert int(td.findtext("segment_size")) == size
