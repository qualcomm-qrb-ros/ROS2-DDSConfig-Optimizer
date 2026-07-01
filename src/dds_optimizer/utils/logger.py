# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Logger: provides a consistent logging interface using Python's standard logging module.

Uses Rich for colorized console output when available.
Log level is controlled by the FASTDDS_OPTIMIZER_LOG_LEVEL environment variable.
Default level: INFO
"""

import logging
import os
import sys
from typing import Optional


# Read log level from environment variable (default: INFO)
_LOG_LEVEL_STR = os.environ.get("FASTDDS_OPTIMIZER_LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_STR, logging.INFO)

# Track whether the root logger has been configured
_configured = False


def _configure_logging() -> None:
    """
    Configure the root logger for the dds_optimizer package.

    Sets up a console handler with a consistent format. Called once on first use.
    """
    global _configured
    if _configured:
        return

    # Get the package root logger
    root_logger = logging.getLogger("dds_optimizer")
    root_logger.setLevel(_LOG_LEVEL)

    # Avoid adding duplicate handlers if already configured
    if root_logger.handlers:
        _configured = True
        return

    # Try to use Rich for pretty console output
    try:
        from rich.logging import RichHandler
        handler = RichHandler(
            rich_tracebacks=True,
            show_path=False,
            markup=True,
        )
        handler.setLevel(_LOG_LEVEL)
        root_logger.addHandler(handler)
    except ImportError:
        # Fall back to standard StreamHandler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(_LOG_LEVEL)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Prevent propagation to the root logger to avoid duplicate messages
    root_logger.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for the given module name.

    This is the main entry point for getting a logger. It ensures the
    package logging is configured before returning the logger.

    Args:
        name: Module name, typically __name__ (e.g., 'dds_optimizer.llm.client').

    Returns:
        Configured Logger instance.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Starting optimization...")
        >>> logger.warning("No active ROS2 nodes found")
        >>> logger.error("LLM API call failed")
    """
    _configure_logging()
    return logging.getLogger(name)


def set_log_level(level: str) -> None:
    """
    Dynamically change the log level for all dds_optimizer loggers.

    Args:
        level: Log level string ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').

    Example:
        >>> set_log_level('DEBUG')  # Enable verbose debug output
        >>> set_log_level('WARNING')  # Suppress info messages
    """
    numeric_level = getattr(logging, level.upper(), None)
    if numeric_level is None:
        raise ValueError(f"Invalid log level: '{level}'")

    root_logger = logging.getLogger("dds_optimizer")
    root_logger.setLevel(numeric_level)
    for handler in root_logger.handlers:
        handler.setLevel(numeric_level)
