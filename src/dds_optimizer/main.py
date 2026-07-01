# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Main CLI entry point for the ROS2 DDSConfig Optimizer.

Usage:
    dds-optimizer run --requirements user_requirements.xml
    dds-optimizer dashboard [--port 5000]

The CLI is built using Python's argparse module for simplicity and zero
additional dependencies beyond what's already in pyproject.toml.
"""

import argparse
import sys
from pathlib import Path

from .utils.logger import get_logger, set_log_level

logger = get_logger(__name__)


def cmd_run(args: argparse.Namespace) -> int:
    """
    Run the optimization workflow.

    Parses user_requirements.xml, collects environment, runs the LLM-driven
    optimization loop, and saves the best DDS configuration found.

    Args:
        args: Parsed CLI arguments with 'requirements' and optional 'session_id'.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    from .optimizer.optimization_loop import run_optimization

    requirements_path = args.requirements
    if not Path(requirements_path).exists():
        logger.error(f"Requirements file not found: {requirements_path}")
        return 1

    logger.info(f"Starting DDS optimization with requirements: {requirements_path}")

    initial_config = getattr(args, "initial_config", None)
    if initial_config and not Path(initial_config).exists():
        logger.error(f"Initial config file not found: {initial_config}")
        return 1

    try:
        session = run_optimization(
            requirements_xml_path=requirements_path,
            session_id=getattr(args, "session_id", None),
            initial_config_path=initial_config,
        )

        from .backends.registry import get_backend
        export_var = "FASTRTPS_DEFAULT_PROFILES_FILE"
        if session.requirements is not None:
            export_var = get_backend(session.requirements.dds_implementation).profiles_env_var

        if session.success:
            print(f"\n✓ Optimization successful!")
            print(f"  Final config: {session.final_config_path}")
            print(f"\nTo apply the optimized configuration:")
            print(f"  export {export_var}={session.final_config_path}")
            return 0
        else:
            print(f"\n⚠ Optimization completed (requirements not fully met).")
            print(f"  Best config: {session.final_config_path}")
            print(f"  Iterations: {len(session.iterations)}")
            best = session.get_best_iteration()
            if best:
                print(f"  Best score: {best.performance_score:.3f}")
            return 0  # Still exit 0 - we saved the best config

    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_dashboard(args: argparse.Namespace) -> int:
    """
    Start the web dashboard for monitoring optimization sessions.

    Args:
        args: Parsed CLI arguments with 'port' and 'host'.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    try:
        import uvicorn
        from .dashboard.backend.api import create_app

        app = create_app()
        port = getattr(args, "port", 5000)
        host = getattr(args, "host", "0.0.0.0")

        print(f"\nStarting DDS Optimizer Dashboard...")
        print(f"  URL: http://localhost:{port}")
        print(f"  Press Ctrl+C to stop\n")

        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    except ImportError as e:
        logger.error(f"Dashboard dependencies not available: {e}")
        logger.error("Install with: pip install fastapi uvicorn")
        return 1
    except Exception as e:
        logger.error(f"Dashboard failed to start: {e}")
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="dds-optimizer",
        description="AI-driven DDS configuration optimizer for ROS2 (FastDDS + CycloneDDS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run optimization with requirements file
  dds-optimizer run --requirements user_requirements.xml

  # Run with verbose logging
  dds-optimizer run --requirements user_requirements.xml --verbose

  # Start the web dashboard
  dds-optimizer dashboard --port 5000
        """,
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- run command ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run the DDS optimization workflow",
    )
    run_parser.add_argument(
        "--requirements", "-r",
        required=True,
        metavar="XML_FILE",
        help="Path to user_requirements.xml",
    )
    run_parser.add_argument(
        "--session-id",
        metavar="ID",
        help="Optional session ID (auto-generated if not provided)",
    )
    run_parser.add_argument(
        "--initial-config",
        required=True,
        metavar="XML_FILE",
        dest="initial_config",
        help=(
            "Path to the initial DDS XML config to use for epoch 1. "
            "The optimizer benchmarks this config, then uses LLM feedback to improve it "
            "from epoch 2 onward."
        ),
    )

    # --- dashboard command ---
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Start the web dashboard",
    )
    dashboard_parser.add_argument(
        "--port", "-p",
        type=int,
        default=5000,
        help="Port to listen on (default: 5000)",
    )
    dashboard_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )

    return parser


def main() -> None:
    """
    Main entry point for the dds-optimizer CLI.

    This function is called when the user runs 'dds-optimizer' from the
    command line (as configured in pyproject.toml [project.scripts]).
    """
    parser = create_parser()
    args = parser.parse_args()

    # Configure log level
    if args.verbose:
        set_log_level("DEBUG")

    # Dispatch to command handler
    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "dashboard":
        sys.exit(cmd_dashboard(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
