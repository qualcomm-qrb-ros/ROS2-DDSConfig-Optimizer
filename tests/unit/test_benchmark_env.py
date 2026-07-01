# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""The benchmark subprocess env must carry the backend's profiles var + RMW."""

from pathlib import Path

from dds_optimizer.benchmark.launcher import _build_benchmark_env


def test_env_sets_cyclonedds_var_and_rmw(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<CycloneDDS/>")
    env = _build_benchmark_env(
        config_path=cfg,
        log_folder=tmp_path,
        log_file_name="benchmark_result",
        profiles_env_var="CYCLONEDDS_URI",
        rmw_implementation="rmw_cyclonedds_cpp",
    )
    assert env["CYCLONEDDS_URI"] == str(cfg.resolve())
    assert env["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"
    assert env["ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER"] == str(tmp_path.resolve())
    assert env["ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME"] == "benchmark_result"


def test_env_sets_fastdds_var_and_rmw(tmp_path):
    cfg = tmp_path / "f.xml"
    cfg.write_text("<dds/>")
    env = _build_benchmark_env(
        config_path=cfg,
        log_folder=tmp_path,
        log_file_name="benchmark_result",
        profiles_env_var="FASTRTPS_DEFAULT_PROFILES_FILE",
        rmw_implementation="rmw_fastrtps_cpp",
    )
    assert env["FASTRTPS_DEFAULT_PROFILES_FILE"] == str(cfg.resolve())
    assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
