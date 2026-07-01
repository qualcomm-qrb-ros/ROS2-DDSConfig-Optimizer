# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
File Utilities: helper functions for file and directory operations.

Optimization history is stored under:
    data/optimization_history/
    └── YYYYMMDD_HHMMSS/          ← one folder per run
        ├── epoch_1/
        │   ├── dds_config.xml
        │   └── benchmark_result.json
        ├── epoch_2/
        │   ├── dds_config.xml
        │   └── benchmark_result.json
        ├── best_config.xml
        └── session_summary.json
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .logger import get_logger

logger = get_logger(__name__)

# Base data directory (relative to the project root)
_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"


def get_data_dir() -> Path:
    """Return the base data directory, creating it if needed."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR


def get_sessions_dir() -> Path:
    """Return the optimization_history directory, creating it if needed."""
    sessions_dir = get_data_dir() / "optimization_history"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_configs_dir() -> Path:
    """Return the configs directory, creating it if needed."""
    configs_dir = get_data_dir() / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    return configs_dir


def create_session_dir(session_id: str) -> Path:
    """
    Create a directory for a specific optimization run.

    The directory name is a timestamp (YYYYMMDD_HHMMSS) for easy sorting.
    The session_id is stored inside session_summary.json.

    Args:
        session_id: Unique session identifier (stored in summary JSON).

    Returns:
        Path to the created session directory.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = get_sessions_dir() / timestamp
    session_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Created session directory: {session_dir}")
    return session_dir


def get_epoch_dir(session_dir: Path, iteration: int) -> Path:
    """
    Get (and create) the epoch subdirectory for a specific iteration.

    Args:
        session_dir: Session directory path.
        iteration: Iteration number (1-based).

    Returns:
        Path to the epoch directory (e.g., session_dir/epoch_1/).
    """
    epoch_dir = session_dir / f"epoch_{iteration}"
    epoch_dir.mkdir(parents=True, exist_ok=True)
    return epoch_dir


def get_config_path(session_dir: Path, iteration: int) -> Path:
    """
    Get the path for the DDS XML config file for a specific epoch.

    Args:
        session_dir: Session directory path.
        iteration: Iteration number (1-based).

    Returns:
        Path for the config file (e.g., session_dir/epoch_1/dds_config.xml).
    """
    return get_epoch_dir(session_dir, iteration) / "dds_config.xml"


def get_benchmark_result_path(session_dir: Path, iteration: int) -> Path:
    """
    Get the path for the benchmark result JSON file for a specific epoch.

    Args:
        session_dir: Session directory path.
        iteration: Iteration number (1-based).

    Returns:
        Path for the result file (e.g., session_dir/epoch_1/benchmark_result.json).
    """
    return get_epoch_dir(session_dir, iteration) / "benchmark_result.json"


def get_final_config_path(session_dir: Path) -> Path:
    """
    Get the path for the final best FastDDS config file.

    Args:
        session_dir: Session directory path.

    Returns:
        Path for the best config (session_dir/best_config.xml).
    """
    return session_dir / "best_config.xml"


def get_session_summary_path(session_dir: Path) -> Path:
    """
    Get the path for the session summary JSON file.

    Args:
        session_dir: Session directory path.

    Returns:
        Path for the summary file (session_dir/session_summary.json).
    """
    return session_dir / "session_summary.json"


def get_conversation_path(session_dir: Path, iteration: int) -> Path:
    """
    Get the path for the LLM conversation Markdown file for a specific epoch.

    The file contains the full prompt sent to the LLM and the full response
    received, formatted as human-readable Markdown.

    Args:
        session_dir: Session directory path.
        iteration: Iteration number (1-based).

    Returns:
        Path for the conversation file
        (e.g., session_dir/epoch_2/llm_conversation.md).
    """
    return get_epoch_dir(session_dir, iteration) / "llm_conversation.md"


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """
    Write JSON data to a file atomically using a temporary file.

    Atomic writes prevent partial writes from corrupting the file if the
    process is interrupted. The data is written to a temp file first,
    then renamed to the target path.

    Args:
        path: Target file path.
        data: Dictionary to serialize as JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file in the same directory
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp",
        suffix=".json",
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        # Atomic rename
        os.replace(tmp_path, path)
        logger.debug(f"Written JSON to: {path}")
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path: Path) -> Dict[str, Any]:
    """
    Read and parse a JSON file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with open(path) as f:
        return json.load(f)


def copy_file(src: Path, dst: Path) -> None:
    """
    Copy a file from src to dst, creating parent directories as needed.

    Args:
        src: Source file path.
        dst: Destination file path.
    """
    import shutil
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    logger.debug(f"Copied {src} → {dst}")
