# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the CycloneDDS structural validator."""

from pathlib import Path

import pytest

from dds_optimizer.backends.cyclonedds.validator import (
    validate_cyclonedds_config,
    CycloneConfigValidationError,
)

WELLFORMED = (
    '<?xml version="1.0" encoding="UTF-8" ?>\n'
    '<CycloneDDS xmlns="https://cdds.io/config">'
    '<Domain Id="any"><Internal><AckDelay>10 ms</AckDelay></Internal></Domain>'
    '</CycloneDDS>'
)


def test_valid_config_has_no_warnings(tmp_path):
    p = tmp_path / "ok.xml"
    p.write_text(WELLFORMED)
    assert validate_cyclonedds_config(p) == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(CycloneConfigValidationError):
        validate_cyclonedds_config(tmp_path / "nope.xml")


def test_malformed_xml_raises(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<CycloneDDS><Domain></CycloneDDS>")  # mismatched tags
    with pytest.raises(CycloneConfigValidationError):
        validate_cyclonedds_config(p)


def test_wrong_root_warns(tmp_path):
    p = tmp_path / "root.xml"
    p.write_text('<NotCyclone xmlns="https://cdds.io/config"><Domain/></NotCyclone>')
    warnings = validate_cyclonedds_config(p)
    assert any("root" in w.lower() for w in warnings)


def test_missing_domain_warns(tmp_path):
    p = tmp_path / "nodomain.xml"
    p.write_text('<CycloneDDS xmlns="https://cdds.io/config"></CycloneDDS>')
    warnings = validate_cyclonedds_config(p)
    assert any("domain" in w.lower() for w in warnings)
