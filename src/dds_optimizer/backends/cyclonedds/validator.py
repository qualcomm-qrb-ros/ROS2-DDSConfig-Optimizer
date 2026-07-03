# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
CycloneDDS config validator (lightweight).

Sparse generation already guarantees structural correctness, so validation only
confirms: file exists, well-formed XML, root local-name is CycloneDDS, and at
least one Domain element is present. Structural problems are non-fatal warnings;
a missing file or malformed XML is a hard error.
"""

import xml.etree.ElementTree as ET
from defusedxml.ElementTree import parse as safe_parse
from pathlib import Path
from typing import List

from ...utils.logger import get_logger

logger = get_logger(__name__)


class CycloneConfigValidationError(Exception):
    """Raised when the CycloneDDS config cannot be read or parsed."""


def _local(tag: str) -> str:
    """Strip an XML namespace prefix: '{ns}Tag' -> 'Tag'."""
    return tag.rsplit("}", 1)[-1]


def validate_cyclonedds_config(config_path: Path) -> List[str]:
    """Validate a CycloneDDS XML config; return a list of warning strings."""
    if not Path(config_path).exists():
        raise CycloneConfigValidationError(f"Config file not found: {config_path}")
    if not Path(config_path).is_file():
        raise CycloneConfigValidationError(f"Config path is not a file: {config_path}")

    try:
        tree = safe_parse(config_path)
    except ET.ParseError as e:
        raise CycloneConfigValidationError(
            f"Malformed CycloneDDS XML '{config_path}': {e}"
        ) from e

    warnings: List[str] = []
    root = tree.getroot()

    if _local(root.tag) != "CycloneDDS":
        warnings.append(
            f"Unexpected root element <{_local(root.tag)}>; expected <CycloneDDS>."
        )

    domains = [c for c in root.iter() if _local(c.tag) == "Domain"]
    if not domains:
        warnings.append("No <Domain> element found in CycloneDDS config.")

    for w in warnings:
        logger.warning(f"CycloneDDS config warning: {w}")
    return warnings
