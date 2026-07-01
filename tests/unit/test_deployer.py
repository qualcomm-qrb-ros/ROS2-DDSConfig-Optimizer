# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the parameterized config deployer env-var handling."""

from pathlib import Path

from dds_optimizer.config import deployer


def test_build_env_defaults_to_fastdds(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<dds/>")
    env = deployer.build_env_for_subprocess(cfg)
    assert env["FASTRTPS_DEFAULT_PROFILES_FILE"] == str(cfg.resolve())


def test_build_env_uses_custom_var(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<CycloneDDS/>")
    env = deployer.build_env_for_subprocess(cfg, env_var="CYCLONEDDS_URI")
    assert env["CYCLONEDDS_URI"] == str(cfg.resolve())


def test_get_export_command_custom_var(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<CycloneDDS/>")
    cmd = deployer.get_export_command(cfg, env_var="CYCLONEDDS_URI")
    assert cmd.startswith("export CYCLONEDDS_URI=")
