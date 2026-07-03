# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Config Validator: validates generated FastDDS XML configuration files.

Checks:
1. File exists and is readable
2. Valid XML syntax
3. Required root element and namespace
4. Required profile sections present (participant, data_writer, data_reader)
5. Transport descriptors are properly defined
"""

import xml.etree.ElementTree as ET
from defusedxml.ElementTree import parse as safe_parse
from pathlib import Path
from typing import List

from ..utils.logger import get_logger

logger = get_logger(__name__)

# FastDDS XML namespace
FASTDDS_NAMESPACE = "http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles"


class ConfigValidationError(Exception):
    """Raised when config validation fails."""
    pass


def validate_config(config_path: Path) -> List[str]:
    """
    Validate a generated FastDDS XML configuration file.

    Args:
        config_path: Path to the FastDDS XML config file.

    Returns:
        List of warning messages (non-fatal). Empty list means no warnings.

    Raises:
        ConfigValidationError: If the config file has critical errors.

    Example:
        >>> warnings = validate_config(Path("/tmp/fastdds_config.xml"))
        >>> print("Config is valid" if not warnings else f"Warnings: {warnings}")
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Check file exists
    if not config_path.exists():
        raise ConfigValidationError(f"Config file not found: {config_path}")
    if not config_path.is_file():
        raise ConfigValidationError(f"Config path is not a file: {config_path}")

    # Parse XML
    try:
        tree = safe_parse(config_path)
    except ET.ParseError as e:
        raise ConfigValidationError(f"Config file is not valid XML: {e}")

    root = tree.getroot()

    # Check root element (with or without namespace)
    root_tag = root.tag
    if root_tag not in ("dds", f"{{{FASTDDS_NAMESPACE}}}dds"):
        errors.append(
            f"Expected root element <dds>, got <{root_tag}>. "
            "The config file may not be a valid FastDDS profile."
        )

    # Check for profiles section
    profiles = root.find("profiles") or root.find(f"{{{FASTDDS_NAMESPACE}}}profiles")
    if profiles is None:
        errors.append("Missing <profiles> section in config file")
    else:
        _validate_profiles(profiles, errors, warnings)

    # Check for library_settings
    lib_settings = (
        root.find("library_settings")
        or root.find(f"{{{FASTDDS_NAMESPACE}}}library_settings")
    )
    if lib_settings is None:
        warnings.append("Missing <library_settings> section (intraprocess_delivery not set)")

    if errors:
        error_msg = f"Config validation failed for '{config_path}':\n"
        error_msg += "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
        raise ConfigValidationError(error_msg)

    logger.debug(f"Config validation passed: {config_path}")
    return warnings


def _validate_profiles(
    profiles: ET.Element,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate the <profiles> section of the config."""

    # Check for transport descriptors
    transport_descriptors = profiles.find("transport_descriptors")
    if transport_descriptors is None:
        warnings.append("No <transport_descriptors> found. Using default transports.")
    else:
        tds = list(transport_descriptors.findall("transport_descriptor"))
        if not tds:
            warnings.append("Empty <transport_descriptors> section")

    # Check for participant profile
    participant = profiles.find("participant")
    if participant is None:
        errors.append("Missing <participant> profile in <profiles> section")
    else:
        _validate_participant(participant, errors, warnings)

    # Check for data_writer profile
    data_writer = profiles.find("data_writer")
    if data_writer is None:
        warnings.append("No <data_writer> profile found. Using FastDDS defaults.")

    # Check for data_reader profile
    data_reader = profiles.find("data_reader")
    if data_reader is None:
        warnings.append("No <data_reader> profile found. Using FastDDS defaults.")


def _validate_participant(
    participant: ET.Element,
    errors: List[str],
    warnings: List[str],
) -> None:
    """Validate the <participant> profile."""
    rtps = participant.find("rtps")
    if rtps is None:
        errors.append("Missing <rtps> element in <participant> profile")
        return

    # Check for userTransports if useBuiltinTransports is false
    use_builtin = rtps.find("useBuiltinTransports")
    if use_builtin is not None and use_builtin.text == "false":
        user_transports = rtps.find("userTransports")
        if user_transports is None or len(list(user_transports)) == 0:
            errors.append(
                "useBuiltinTransports is 'false' but no <userTransports> are defined. "
                "This will result in no transport being available."
            )
