# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the backend registry and the two concrete backends."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dds_optimizer.backends.registry import get_backend
from dds_optimizer.backends.base import DDSBackend


def test_get_fastdds_backend():
    b = get_backend("fastdds")
    assert isinstance(b, DDSBackend)
    assert b.name == "fastdds"
    assert b.profiles_env_var == "FASTRTPS_DEFAULT_PROFILES_FILE"
    assert b.rmw_implementation == "rmw_fastrtps_cpp"


def test_get_cyclonedds_backend():
    b = get_backend("cyclonedds")
    assert isinstance(b, DDSBackend)
    assert b.name == "cyclonedds"
    assert b.profiles_env_var == "CYCLONEDDS_URI"
    assert b.rmw_implementation == "rmw_cyclonedds_cpp"


def test_get_backend_is_case_insensitive():
    assert get_backend("FastDDS").name == "fastdds"


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        get_backend("nosuchdds")


def test_knowledge_base_paths_exist():
    for name in ("fastdds", "cyclonedds"):
        kb = get_backend(name).knowledge_base_path()
        assert kb.exists(), f"{name} KB not found at {kb}"


def test_prompt_expertise_mentions_vendor():
    assert "fast" in get_backend("fastdds").prompt_expertise().lower()
    assert "cyclone" in get_backend("cyclonedds").prompt_expertise().lower()


def test_cyclonedds_backend_generates_and_validates(tmp_path):
    b = get_backend("cyclonedds")
    out = tmp_path / "c.xml"
    b.generate_config({"ack_delay": "10 ms"}, out)
    assert out.exists()
    assert b.validate_config(out) == []
    root = ET.parse(out).getroot()
    assert root.tag.endswith("CycloneDDS")


def test_fastdds_backend_generates_and_validates(tmp_path):
    b = get_backend("fastdds")
    out = tmp_path / "f.xml"
    b.generate_config({"history_depth": 10, "reliability_kind": "RELIABLE"}, out)
    assert out.exists()
    # FastDDS validator returns a (possibly empty) list of warnings.
    assert isinstance(b.validate_config(out), list)
