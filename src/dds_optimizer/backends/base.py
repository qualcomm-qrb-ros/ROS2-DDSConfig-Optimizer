# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
DDSBackend: the abstraction that isolates all vendor-specific behavior.

The shared optimizer core (loop, LLM, benchmark, prompt builder) interacts
only with a DDSBackend instance for the steps that differ between DDS
implementations:
  - which knowledge base file to load,
  - the system-prompt opening line + any format notes,
  - how to generate a config file from a params dict,
  - how to validate that config file,
  - the environment variable a benchmark subprocess must set to load the
    config, and the RMW implementation ROS2 must use.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List


class DDSBackend(ABC):
    """Abstract base for a DDS vendor backend."""

    #: Vendor identifier, e.g. "fastdds" | "cyclonedds".
    name: str
    #: Env var pointing at the profiles/config file the DDS impl reads.
    profiles_env_var: str
    #: RMW implementation ROS2 must use for this vendor.
    rmw_implementation: str

    @abstractmethod
    def knowledge_base_path(self) -> Path:
        """Absolute path to this backend's performance_critical_params.json."""

    @abstractmethod
    def prompt_expertise(self) -> str:
        """System-prompt opening line + any vendor-specific format notes."""

    @abstractmethod
    def generate_config(self, params: Dict, out_path: Path) -> Path:
        """Generate a vendor config file from a param name->value dict."""

    @abstractmethod
    def validate_config(self, config_path: Path) -> List[str]:
        """Validate a generated config; return a list of warning strings."""
