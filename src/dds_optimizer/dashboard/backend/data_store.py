# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Data Store: reads optimization history from the filesystem.

History is stored under:
    data/optimization_history/
    └── YYYYMMDD_HHMMSS/
        ├── epoch_1/
        │   ├── fastdds_config.xml
        │   └── benchmark_result.json
        ├── epoch_2/
        │   ├── fastdds_config.xml
        │   └── benchmark_result.json
        ├── best_config.xml
        └── session_summary.json
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.file_utils import get_sessions_dir
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Summary filename inside each run directory
_SUMMARY_FILE = "session_summary.json"
# Final best config filename
_BEST_CONFIG_FILE = "best_config.xml"


def list_sessions() -> List[Dict[str, Any]]:
    """
    List all optimization runs with summary information.

    Returns:
        List of run summary dicts, sorted by start time (newest first).
        Each dict contains: session_id, run_dir (timestamp), started_at,
        completed_at, success, epochs_count, best_score, final_config_path.
    """
    history_dir = get_sessions_dir()
    summaries = []

    for run_dir in sorted(history_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        summary_file = run_dir / _SUMMARY_FILE
        if not summary_file.exists():
            continue

        try:
            with open(summary_file) as f:
                state = json.load(f)

            iterations = state.get("iterations", [])
            best_score = max(
                (it.get("performance_score", 0) for it in iterations),
                default=0,
            )

            summaries.append({
                "session_id": state.get("session_id", run_dir.name),
                "run_dir": run_dir.name,          # YYYYMMDD_HHMMSS
                "started_at": state.get("started_at"),
                "completed_at": state.get("completed_at"),
                "success": state.get("success", False),
                "converged": state.get("converged", False),
                "epochs_count": len(iterations),
                "best_score": round(best_score, 4),
                "final_config_path": state.get("final_config_path"),
                "run_path": str(run_dir),
            })
        except Exception as e:
            logger.warning(f"Failed to load run from {run_dir}: {e}")

    return summaries


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the full state of a specific optimization run.

    Looks up by session_id (UUID) or by run_dir timestamp.

    Args:
        session_id: Session ID (UUID) or run directory name (YYYYMMDD_HHMMSS).

    Returns:
        Full session state dict, or None if not found.
    """
    history_dir = get_sessions_dir()

    for run_dir in history_dir.iterdir():
        if not run_dir.is_dir():
            continue
        # Match by run_dir name (timestamp) or session_id inside the JSON
        if session_id != run_dir.name and session_id not in run_dir.name:
            # Try reading the summary to check session_id
            summary_file = run_dir / _SUMMARY_FILE
            if not summary_file.exists():
                continue
            try:
                with open(summary_file) as f:
                    state = json.load(f)
                if state.get("session_id") != session_id:
                    continue
            except Exception:
                continue
        else:
            summary_file = run_dir / _SUMMARY_FILE
            if not summary_file.exists():
                continue

        try:
            with open(summary_file) as f:
                state = json.load(f)
            # Attach run_dir for convenience
            state["run_dir"] = run_dir.name
            state["run_path"] = str(run_dir)
            return state
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    return None


def get_session_iterations(session_id: str) -> List[Dict[str, Any]]:
    """
    Get the epoch history for a specific optimization run.

    Args:
        session_id: Session ID or run directory name.

    Returns:
        List of epoch dicts with metrics and scores.
    """
    state = get_session(session_id)
    if not state:
        return []
    return state.get("iterations", [])


def get_config_content(session_id: str, iteration: Optional[int] = None) -> Optional[str]:
    """
    Get the XML content of a FastDDS config for a run.

    Args:
        session_id: Session ID or run directory name.
        iteration: Epoch number (1-based). If None, returns best_config.xml.

    Returns:
        XML content string, or None if not found.
    """
    state = get_session(session_id)
    if not state:
        return None

    if iteration is None:
        # Return best_config.xml
        config_path = state.get("final_config_path")
        if not config_path:
            # Fallback: look for best_config.xml in run_path
            run_path = state.get("run_path")
            if run_path:
                fallback = Path(run_path) / _BEST_CONFIG_FILE
                if fallback.exists():
                    config_path = str(fallback)
    else:
        # Return epoch_N/fastdds_config.xml
        iterations = state.get("iterations", [])
        if iteration < 1 or iteration > len(iterations):
            return None
        config_path = iterations[iteration - 1].get("config_path")

    if not config_path or not Path(config_path).exists():
        return None

    try:
        return Path(config_path).read_text()
    except Exception as e:
        logger.error(f"Failed to read config file {config_path}: {e}")
        return None
