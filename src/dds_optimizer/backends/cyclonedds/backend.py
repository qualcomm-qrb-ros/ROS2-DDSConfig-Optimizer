# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""CycloneDDS backend — generic generator + lightweight validator."""

import json
from pathlib import Path
from typing import Dict, List

from ...utils.logger import get_logger
from ..base import DDSBackend
from .generator import generate_cyclonedds_config
from .validator import validate_cyclonedds_config

logger = get_logger(__name__)

_KB_PATH = (
    Path(__file__).resolve().parents[4]
    / "data" / "knowledge_base" / "cyclonedds" / "performance_critical_params.json"
)


class CycloneDDSBackend(DDSBackend):
    name = "cyclonedds"
    profiles_env_var = "CYCLONEDDS_URI"
    rmw_implementation = "rmw_cyclonedds_cpp"

    def __init__(self) -> None:
        self._kb_cache: Dict = {}

    def knowledge_base_path(self) -> Path:
        return _KB_PATH

    def _kb(self) -> Dict:
        if not self._kb_cache:
            with open(self.knowledge_base_path()) as f:
                self._kb_cache = json.load(f)
            logger.debug(f"Loaded CycloneDDS knowledge base: {self.knowledge_base_path()}")
        return self._kb_cache

    def prompt_expertise(self) -> str:
        return (
            "You are an expert in Eclipse CycloneDDS configuration optimization "
            "for ROS2.\n"
            "NOTE: CycloneDDS parameter values are unit-suffixed strings, e.g. "
            '"8 MiB", "100 ms", "65500B". Emit values in that form.'
        )

    def generate_config(self, params: Dict, out_path: Path) -> Path:
        return generate_cyclonedds_config(dict(params), self._kb(), out_path)

    def validate_config(self, config_path: Path) -> List[str]:
        return validate_cyclonedds_config(config_path)
