# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Benchmark Launcher: runs ros2_benchmark tests with a specific FastDDS configuration.

How it works:
1. Sets FASTRTPS_DEFAULT_PROFILES_FILE to the optimized config path
2. Sets ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER to a known output directory
3. Sets ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME to a predictable filename
4. Runs: launch_test /path/to/benchmark.py
5. While the benchmark is running, a background thread collects the live
   ROS2 pipeline topology (nodes + topic connections) after a short startup
   delay to let the pipeline nodes initialize.
6. Waits for completion and returns (result_path, pipeline_topology).

The benchmark subprocess inherits the environment variables, so FastDDS
automatically uses the optimized configuration during the test.

Environment variables used:
    FASTRTPS_DEFAULT_PROFILES_FILE      → FastDDS config to use
    ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER  → Where to write results JSON
    ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME → Filename for results JSON
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

from ..environment.collector import collect_pipeline_topology
from ..models import BenchmarkConfig, PipelineTopology
from ..utils.logger import get_logger

logger = get_logger(__name__)

# ros2_benchmark environment variable overrides for output location
ROS2_BENCHMARK_LOG_FOLDER_ENV = "ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER"
ROS2_BENCHMARK_LOG_FILE_ENV = "ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME"

# Default timeout for benchmark runs (seconds)
DEFAULT_BENCHMARK_TIMEOUT = 600  # 10 minutes

# Delay before collecting pipeline topology (seconds) — lets nodes initialize
TOPOLOGY_COLLECTION_DELAY = 5

# Polling interval between topology collection attempts (seconds)
TOPOLOGY_POLL_INTERVAL = 3

# Maximum number of topology collection attempts before giving up
TOPOLOGY_MAX_ATTEMPTS = 10


class BenchmarkLaunchError(Exception):
    """Raised when the benchmark fails to launch or complete."""
    pass


def run_benchmark(
    benchmark_config: BenchmarkConfig,
    config_path: Path,
    epoch_dir: Path,
    iteration: int,
    profiles_env_var: str = "FASTRTPS_DEFAULT_PROFILES_FILE",
    rmw_implementation: str = "rmw_fastrtps_cpp",
    timeout: int = DEFAULT_BENCHMARK_TIMEOUT,
) -> Tuple[Path, Optional[PipelineTopology]]:
    """
    Run a ros2_benchmark test with the specified FastDDS configuration.

    This function:
    1. Prepares the environment with the FastDDS config and output paths
    2. Starts the benchmark subprocess
    3. Collects the live pipeline topology in a background thread
       (after TOPOLOGY_COLLECTION_DELAY seconds to let nodes initialize)
    4. Waits for the benchmark to complete
    5. Returns (result_json_path, pipeline_topology)

    The result is written to:
        epoch_dir/benchmark_result.json

    Args:
        benchmark_config: Benchmark configuration (test file path, launch command).
        config_path: Path to the DDS XML config to use.
        epoch_dir: Epoch directory where benchmark_result.json will be written.
        iteration: Current iteration number (used for logging only).
        profiles_env_var: Env var the DDS vendor reads for its config file.
        rmw_implementation: RMW implementation ROS2 must use.
        timeout: Maximum seconds to wait for the benchmark to complete.

    Returns:
        Tuple of:
        - Path to the benchmark result JSON file (epoch_dir/benchmark_result.json)
        - PipelineTopology collected during the run (None if collection failed)

    Raises:
        BenchmarkLaunchError: If the benchmark fails to run or times out.
        FileNotFoundError: If the benchmark test file or config file doesn't exist.
    """
    # Validate inputs
    test_file = Path(benchmark_config.test_file)
    if not test_file.exists():
        raise FileNotFoundError(f"Benchmark test file not found: {test_file}")

    if not config_path.exists():
        raise FileNotFoundError(f"DDS config file not found: {config_path}")

    # Prepare epoch directory
    epoch_dir.mkdir(parents=True, exist_ok=True)

    # Fixed result filename — ros2_benchmark appends .json automatically
    result_filename = "benchmark_result"
    result_json_path = epoch_dir / f"{result_filename}.json"

    # Build the environment for the subprocess
    env = _build_benchmark_env(
        config_path=config_path,
        log_folder=epoch_dir,
        log_file_name=result_filename,
        profiles_env_var=profiles_env_var,
        rmw_implementation=rmw_implementation,
    )

    # Build the command
    cmd = [benchmark_config.launch_command, str(test_file)]

    logger.info(f"Running benchmark (epoch {iteration}): {' '.join(cmd)}")
    logger.info(f"  DDS config: {config_path}")
    logger.info(f"  Expected result: {result_json_path}")

    start_time = time.time()

    # Container for topology result from background thread
    topology_result: dict = {"topology": None}

    def _collect_topology_in_background():
        """Background thread: poll until pipeline nodes appear, then record topology.

        Strategy:
        - Wait TOPOLOGY_COLLECTION_DELAY seconds for initial node startup
        - Then poll every TOPOLOGY_POLL_INTERVAL seconds up to TOPOLOGY_MAX_ATTEMPTS
        - Stop early as soon as at least one pipeline node is discovered
        - Always store the last successfully collected topology so the caller
          gets the best available result even if nodes are never found
        """
        # Initial startup delay before the first poll
        time.sleep(TOPOLOGY_COLLECTION_DELAY)

        last_topology = None
        for attempt in range(1, TOPOLOGY_MAX_ATTEMPTS + 1):
            try:
                topology = collect_pipeline_topology()
                last_topology = topology
                if topology.nodes and topology.topics:
                    topology_result["topology"] = topology
                    logger.info(
                        f"Pipeline topology collected (attempt {attempt}/{TOPOLOGY_MAX_ATTEMPTS}): "
                        f"{len(topology.nodes)} nodes, {len(topology.topics)} topics"
                    )
                    return
                if topology.nodes and not topology.topics:
                    logger.debug(
                        f"Topology poll {attempt}/{TOPOLOGY_MAX_ATTEMPTS}: "
                        f"{len(topology.nodes)} nodes found but 0 topics yet, retrying..."
                    )
                else:
                    logger.debug(
                        f"Topology poll {attempt}/{TOPOLOGY_MAX_ATTEMPTS}: "
                        "no pipeline nodes found yet, retrying..."
                    )
            except Exception as e:
                logger.warning(
                    f"Topology poll {attempt}/{TOPOLOGY_MAX_ATTEMPTS} failed: {e}"
                )

            # Only sleep between attempts (not after the last one)
            if attempt < TOPOLOGY_MAX_ATTEMPTS:
                time.sleep(TOPOLOGY_POLL_INTERVAL)

        # Exhausted all attempts — store whatever we last collected
        if last_topology is not None:
            topology_result["topology"] = last_topology
        logger.warning(
            f"Topology collection gave up after {TOPOLOGY_MAX_ATTEMPTS} attempts "
            f"({TOPOLOGY_COLLECTION_DELAY + (TOPOLOGY_MAX_ATTEMPTS - 1) * TOPOLOGY_POLL_INTERVAL}s total). "
            "Topology context may be incomplete in LLM prompt."
        )

    # Start topology collection thread before launching benchmark
    topology_thread = threading.Thread(
        target=_collect_topology_in_background,
        daemon=True,
        name=f"topology-collector-epoch-{iteration}",
    )
    topology_thread.start()

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=False,  # Let output go to terminal for visibility
            timeout=timeout,
            text=True,
        )
    except subprocess.TimeoutExpired:
        raise BenchmarkLaunchError(
            f"Benchmark timed out after {timeout} seconds. "
            f"Command: {' '.join(cmd)}"
        )
    except FileNotFoundError:
        raise BenchmarkLaunchError(
            f"Launch command '{benchmark_config.launch_command}' not found. "
            "Make sure ros2_benchmark is installed and ROS2 is sourced."
        )
    except OSError as e:
        raise BenchmarkLaunchError(
            f"Failed to run benchmark: {e}. "
            f"Command: {' '.join(cmd)}"
        )

    elapsed = time.time() - start_time
    logger.info(f"Benchmark completed in {elapsed:.1f}s (exit code: {result.returncode})")

    # Wait for topology thread to finish (give it the full polling window + buffer)
    topology_join_timeout = TOPOLOGY_COLLECTION_DELAY + TOPOLOGY_MAX_ATTEMPTS * TOPOLOGY_POLL_INTERVAL + 5
    topology_thread.join(timeout=topology_join_timeout)
    pipeline_topology: Optional[PipelineTopology] = topology_result["topology"]

    # Check exit code
    if result.returncode != 0:
        logger.warning(
            f"Benchmark exited with non-zero code {result.returncode}. "
            "Results may be incomplete."
        )

    # Check if result file was created
    if not result_json_path.exists():
        # Try to find any recently created JSON file in the epoch dir first,
        # then fall back to searching the parent session directory (in case
        # ros2_benchmark wrote to a sibling epoch dir due to timing).
        fallback = _find_latest_result_json(epoch_dir)
        if fallback is None:
            fallback = _find_latest_result_json(epoch_dir.parent)
        if fallback:
            logger.warning(
                f"Expected result file not found at {result_json_path}. "
                f"Using fallback: {fallback}"
            )
            return fallback, pipeline_topology
        else:
            raise BenchmarkLaunchError(
                f"Benchmark completed but no result file found at: {result_json_path}. "
                "The benchmark may have failed to write results. "
                "Check the benchmark output above for errors."
            )

    # Pretty-print the result JSON for human readability
    _pretty_print_json(result_json_path)

    logger.info(f"Benchmark result written to: {result_json_path}")
    return result_json_path, pipeline_topology


def _build_benchmark_env(
    config_path: Path,
    log_folder: Path,
    log_file_name: str,
    profiles_env_var: str = "FASTRTPS_DEFAULT_PROFILES_FILE",
    rmw_implementation: str = "rmw_fastrtps_cpp",
) -> dict:
    """
    Build the environment dictionary for the benchmark subprocess.

    Sets:
    - <profiles_env_var>: DDS config file the vendor reads
      (FASTRTPS_DEFAULT_PROFILES_FILE or CYCLONEDDS_URI)
    - RMW_IMPLEMENTATION: the RMW ROS2 must use (essential for CycloneDDS to
      read the config at all)
    - ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER / _FILE_NAME: result location
    """
    env = os.environ.copy()
    env[profiles_env_var] = str(config_path.resolve())
    env["RMW_IMPLEMENTATION"] = rmw_implementation
    env[ROS2_BENCHMARK_LOG_FOLDER_ENV] = str(log_folder.resolve())
    env[ROS2_BENCHMARK_LOG_FILE_ENV] = log_file_name
    return env


def _pretty_print_json(json_path: Path) -> None:
    """Rewrite a JSON file with 2-space indentation for human readability."""
    try:
        with open(json_path) as f:
            data = json.load(f)
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to pretty-print result JSON: {e}")


def _find_latest_result_json(directory: Path) -> Optional[Path]:
    """
    Find the most recently created JSON file in a directory.

    This is a fallback for when the expected result file is not found.
    ros2_benchmark may use a different filename than expected.

    Args:
        directory: Directory to search for JSON files.

    Returns:
        Path to the most recently modified JSON file, or None if none found.
    """
    json_files = list(directory.glob("*.json"))
    if not json_files:
        return None

    # Return the most recently modified file
    return max(json_files, key=lambda p: p.stat().st_mtime)
