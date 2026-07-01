# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""FastDDS backend — wraps the hand-written FastDDS generator and validator."""

from pathlib import Path
from typing import Dict, List

from ...config.generator import generate_fastdds_config
from ...config.validator import validate_config as validate_fastdds_config
from ...models import DDSParameterSet
from ..base import DDSBackend

# FastDDS KB lives under data/knowledge_base/fastdds/. This file is at
# src/dds_optimizer/backends/fastdds/backend.py → parents[4] is the repo root.
_KB_PATH = (
    Path(__file__).resolve().parents[4]
    / "data" / "knowledge_base" / "fastdds" / "performance_critical_params.json"
)


class FastDDSBackend(DDSBackend):
    name = "fastdds"
    profiles_env_var = "FASTRTPS_DEFAULT_PROFILES_FILE"
    rmw_implementation = "rmw_fastrtps_cpp"

    def knowledge_base_path(self) -> Path:
        return _KB_PATH

    def prompt_expertise(self) -> str:
        return (
            "You are an expert in FastDDS (eProsima Fast DDS) configuration "
            "optimization for ROS2."
        )

    def generate_config(self, params: Dict, out_path: Path) -> Path:
        return generate_fastdds_config(DDSParameterSet(parameters=dict(params)), out_path)

    def validate_config(self, config_path: Path) -> List[str]:
        return validate_fastdds_config(config_path)
