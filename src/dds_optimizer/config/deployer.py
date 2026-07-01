# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Config Deployer: manages the deployment of FastDDS configuration files.

FastDDS reads its configuration from the file pointed to by the environment variable:
    FASTRTPS_DEFAULT_PROFILES_FILE=/path/to/fastdds_config.xml

This module provides functions to:
1. Set this environment variable for the current process (affects child processes)
2. Generate shell export commands for manual use
3. Restore the previous configuration after testing

Usage in the optimization loop:
    1. deployer.set_fastdds_config(config_path)  → sets env var
    2. benchmark.run()                            → benchmark inherits env var
    3. deployer.restore_previous_config()         → restores original env var
"""

import os
from pathlib import Path
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)

# The FastDDS environment variable name
FASTDDS_PROFILES_ENV_VAR = "FASTRTPS_DEFAULT_PROFILES_FILE"

# Store the original value so we can restore it
_original_config_path: Optional[str] = None


def set_fastdds_config(config_path: Path) -> None:
    """
    Set the FASTRTPS_DEFAULT_PROFILES_FILE environment variable.

    This makes FastDDS use the specified configuration file for all
    subsequent DDS operations in the current process and its children.

    The previous value is saved so it can be restored with
    restore_previous_config().

    Args:
        config_path: Path to the FastDDS XML configuration file.

    Raises:
        FileNotFoundError: If the config file does not exist.

    Example:
        >>> set_fastdds_config(Path("/tmp/optimized_fastdds.xml"))
        >>> # Now run benchmark - it will use this config
        >>> run_benchmark()
        >>> restore_previous_config()
    """
    global _original_config_path

    if not config_path.exists():
        raise FileNotFoundError(
            f"FastDDS config file not found: {config_path}. "
            "Cannot set FASTRTPS_DEFAULT_PROFILES_FILE."
        )

    # Save the current value before overwriting
    _original_config_path = os.environ.get(FASTDDS_PROFILES_ENV_VAR)

    # Set the new config path
    os.environ[FASTDDS_PROFILES_ENV_VAR] = str(config_path.resolve())

    logger.info(
        f"Set {FASTDDS_PROFILES_ENV_VAR}={config_path.resolve()}"
    )


def restore_previous_config() -> None:
    """
    Restore the FASTRTPS_DEFAULT_PROFILES_FILE to its previous value.

    If there was no previous value, the environment variable is unset.
    This should be called after each benchmark run to clean up.

    Example:
        >>> set_fastdds_config(Path("/tmp/config.xml"))
        >>> run_benchmark()
        >>> restore_previous_config()  # Clean up
    """
    global _original_config_path

    if _original_config_path is not None:
        os.environ[FASTDDS_PROFILES_ENV_VAR] = _original_config_path
        logger.debug(
            f"Restored {FASTDDS_PROFILES_ENV_VAR}={_original_config_path}"
        )
    else:
        # Remove the variable if it wasn't set before
        os.environ.pop(FASTDDS_PROFILES_ENV_VAR, None)
        logger.debug(f"Unset {FASTDDS_PROFILES_ENV_VAR}")

    _original_config_path = None


def get_current_config() -> Optional[str]:
    """
    Get the currently active FastDDS configuration file path.

    Returns:
        Path string if FASTRTPS_DEFAULT_PROFILES_FILE is set, None otherwise.
    """
    return os.environ.get(FASTDDS_PROFILES_ENV_VAR)


def get_export_command(config_path: Path) -> str:
    """
    Generate a shell export command for manual use.

    This is useful for displaying to the user so they can manually apply
    the optimized configuration in their own shell sessions.

    Args:
        config_path: Path to the FastDDS XML configuration file.

    Returns:
        Shell export command string.

    Example:
        >>> cmd = get_export_command(Path("/data/configs/optimized.xml"))
        >>> print(cmd)
        export FASTRTPS_DEFAULT_PROFILES_FILE=/data/configs/optimized.xml
    """
    return f"export {FASTDDS_PROFILES_ENV_VAR}={config_path.resolve()}"


def build_env_for_subprocess(config_path: Path) -> dict:
    """
    Build an environment dictionary for subprocess calls with the config set.

    This is used by the benchmark launcher to pass the config path to the
    benchmark subprocess without modifying the current process environment.

    Args:
        config_path: Path to the FastDDS XML configuration file.

    Returns:
        Dictionary of environment variables with FASTRTPS_DEFAULT_PROFILES_FILE set.

    Example:
        >>> env = build_env_for_subprocess(Path("/tmp/config.xml"))
        >>> subprocess.run(["launch_test", "benchmark.py"], env=env)
    """
    env = os.environ.copy()
    env[FASTDDS_PROFILES_ENV_VAR] = str(config_path.resolve())
    return env
