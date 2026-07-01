# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Registry mapping a vendor name to a DDSBackend instance."""

from .base import DDSBackend
from .cyclonedds.backend import CycloneDDSBackend
from .fastdds.backend import FastDDSBackend

SUPPORTED_BACKENDS = ("fastdds", "cyclonedds")


def get_backend(name: str) -> DDSBackend:
    """
    Return a DDSBackend instance for the given vendor name (case-insensitive).

    Raises:
        ValueError: if name is not a supported backend.
    """
    key = (name or "").strip().lower()
    if key == "fastdds":
        return FastDDSBackend()
    if key == "cyclonedds":
        return CycloneDDSBackend()
    raise ValueError(
        f"Unsupported DDS implementation '{name}'. "
        f"Must be one of: {SUPPORTED_BACKENDS}."
    )
