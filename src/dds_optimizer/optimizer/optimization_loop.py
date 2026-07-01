# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Optimization Loop: orchestrates the full FastDDS configuration optimization workflow.

Workflow:
    Phase 1: Parse requirements → Collect environment → Validate both
    Phase 2: Epoch 1 uses the user-provided --initial-config directly (no LLM call)
    Phase 3: Run benchmark (with background topology collection) → Parse results → Evaluate
    Phase 4: If requirements met → stop immediately (success)
             If not met AND epochs < max → LLM generates improved params → repeat Phase 3
    Phase 5: Save best config → Update session → Print highlighted summary

The LLM outputs a structured JSON object:
    {"set": {"param": value, ...}, "delete": ["param", ...]}

The system generates the complete FastDDS XML config from the accumulated params
using config/generator.py. "delete" params are removed from the accumulated dict,
reverting them to template defaults.

Output structure:
    data/optimization_history/YYYYMMDD_HHMMSS/
    ├── epoch_1/
    │   ├── fastdds_config.xml
    │   └── benchmark_result.json
    ├── epoch_2/
    │   ├── fastdds_config.xml
    │   ├── benchmark_result.json
    │   └── llm_conversation.md    ← full prompt + response (human-readable)
    ├── best_config.xml
    └── session_summary.json
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..benchmark.launcher import run_benchmark
from ..benchmark.results_parser import parse_benchmark_results
from ..config.generator import generate_fastdds_config
from ..environment.collector import collect_environment
from ..environment.validator import validate_environment
from ..llm.llm_client import call_llm
from ..llm.prompt_builder import build_feedback_prompt
from ..llm.response_parser import parse_llm_response
from ..models import (
    DDSParameterSet,
    EnvironmentInfo,
    OptimizationIteration,
    OptimizationSession,
    PipelineTopology,
    RequirementsConfig,
    TopicInfo,
)
from ..requirements.parser import parse_requirements
from ..requirements.validator import validate_requirements
from ..utils.file_utils import (
    create_session_dir,
    get_config_path,
    get_conversation_path,
    get_epoch_dir,
    get_final_config_path,
    get_session_summary_path,
    write_json_atomic,
)
from ..utils.logger import get_logger
from .evaluator import check_convergence, evaluate_results
from .feedback_builder import build_performance_gaps

logger = get_logger(__name__)

# Maximum LLM retry attempts for invalid responses
MAX_LLM_PARSE_RETRIES = 3


def run_optimization(
    requirements_xml_path: str,
    session_id: Optional[str] = None,
    initial_config_path: Optional[str] = None,
) -> OptimizationSession:
    """
    Run the complete FastDDS configuration optimization workflow.

    This is the main entry point for the optimization process. It:
    1. Parses and validates user requirements
    2. Collects and validates system environment
    3. Runs the optimization loop:
       - Epoch 1: benchmarks the user-provided --initial-config
       - Epoch 2+: LLM generates improved XML configs based on benchmark feedback
       - Stops immediately when all required metrics are met
    4. Saves the best configuration found
    5. Prints a highlighted per-requirement summary

    Args:
        requirements_xml_path: Path to the user_requirements.xml file.
        session_id: Optional session ID. If None, a new UUID is generated.
        initial_config_path: Required path to the initial FastDDS XML config.
                             Epoch 1 benchmarks this config directly (no LLM call).

    Returns:
        OptimizationSession with complete history of all iterations.
    """
    if not initial_config_path:
        raise ValueError(
            "--initial-config is required. Please provide a FastDDS XML config file "
            "to use as the starting point for optimization."
        )

    # Create session
    session = OptimizationSession()
    if session_id:
        session.session_id = session_id

    logger.info(f"Starting optimization session: {session.session_id}")

    # Create session directory for storing configs and results
    session_dir = create_session_dir(session.session_id)
    logger.info(f"Session directory: {session_dir}")

    try:
        # ===================================================================
        # Phase 1: Requirements & Environment
        # ===================================================================
        logger.info("Phase 1: Parsing requirements and collecting environment...")

        requirements = _parse_and_validate_requirements(requirements_xml_path)
        session.requirements = requirements

        env = _collect_and_validate_environment(requirements)
        session.environment = env

        _save_session_state(session, session_dir)

        # ===================================================================
        # Phase 2-4: Optimization Loop
        # ===================================================================
        logger.info("Phase 2: Starting optimization loop...")

        session = _run_optimization_loop(
            session=session,
            requirements=requirements,
            env=env,
            session_dir=session_dir,
            initial_config_path=initial_config_path,
        )

        # ===================================================================
        # Phase 5: Finalization
        # ===================================================================
        session.completed_at = datetime.now()

        # Save the best config as best_config.xml
        best_iter = session.get_best_iteration()
        if best_iter and Path(best_iter.config_path).exists():
            final_config_path = get_final_config_path(session_dir)
            shutil.copy2(best_iter.config_path, final_config_path)
            session.final_config_path = str(final_config_path)
            logger.info(f"Best config saved to: {final_config_path}")

        _save_session_state(session, session_dir)

        # Print highlighted summary
        _print_optimization_summary(session, requirements)

    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        session.completed_at = datetime.now()
        # Save the best config found so far (if any epochs completed successfully)
        best_iter = session.get_best_iteration()
        if best_iter and Path(best_iter.config_path).exists():
            final_config_path = get_final_config_path(session_dir)
            shutil.copy2(best_iter.config_path, final_config_path)
            session.final_config_path = str(final_config_path)
            logger.info(f"Best config saved to: {final_config_path}")
        _save_session_state(session, session_dir)
        raise

    return session


def _parse_and_validate_requirements(xml_path: str) -> RequirementsConfig:
    """Parse and validate user requirements XML."""
    logger.info(f"Parsing requirements from: {xml_path}")
    requirements = parse_requirements(xml_path)

    logger.info("Validating requirements...")
    warnings = validate_requirements(requirements)
    for w in warnings:
        logger.warning(f"Requirements warning: {w}")

    logger.info(
        f"Requirements parsed: benchmark={requirements.benchmark.test_file}, "
        f"max_iterations={requirements.optimization_settings.max_iterations}, "
        f"llm={requirements.llm_config.provider}/{requirements.llm_config.model}"
    )
    return requirements


def _collect_and_validate_environment(requirements: RequirementsConfig) -> EnvironmentInfo:
    """Collect and validate system environment."""
    logger.info("Collecting environment information...")
    env = collect_environment(requirements.performance_requirements)

    logger.info(
        f"Environment: OS={env.os_version}, ROS2={env.ros2_distro}, "
        f"nodes={len(env.active_nodes)}, topics={len(env.active_topics)}"
    )

    logger.info("Validating environment...")
    warnings = validate_environment(env, requirements)
    for w in warnings:
        logger.warning(f"Environment warning: {w}")

    return env


def _run_optimization_loop(
    session: OptimizationSession,
    requirements: RequirementsConfig,
    env: EnvironmentInfo,
    session_dir: Path,
    initial_config_path: str,
) -> OptimizationSession:
    """
    Run the main optimization loop.

    Epoch 1: copy initial_config_path → epoch_1/fastdds_config.xml, run benchmark.
    Epoch 2+: LLM generates improved params → apply set/delete → generate XML → run benchmark.

    The pipeline topology is collected in a background thread during each benchmark run.

    Stops when:
    - All required metrics are met (success)
    - max_iterations reached
    - 3 consecutive benchmark failures
    """
    max_iterations = requirements.optimization_settings.max_iterations
    convergence_threshold = requirements.optimization_settings.convergence_threshold

    # current_config_params accumulates all LLM-set parameters across epochs.
    # "delete" operations remove entries from this dict (revert to template defaults).
    # For epoch 1 (initial config), this starts empty since no LLM was involved.
    current_config_params: dict = {}
    previous_score = 0.0
    consecutive_failures = 0
    last_benchmark_error: Optional[str] = None
    last_pipeline_topology: Optional[PipelineTopology] = None

    for iteration in range(1, max_iterations + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"Optimization Epoch {iteration}/{max_iterations}")
        logger.info(f"{'='*60}")

        # -------------------------------------------------------------------
        # Step 1: Prepare config for this epoch
        # -------------------------------------------------------------------
        config_path = get_config_path(session_dir, iteration)
        params_set_this_epoch: dict = {}
        params_deleted_this_epoch: list = []

        if iteration == 1:
            # Epoch 1: copy the user-provided initial config directly
            logger.info(f"Epoch 1: using provided initial config: {initial_config_path}")
            shutil.copy2(initial_config_path, config_path)
            llm_reasoning = "[initial config provided by user]"
        else:
            # Epoch 2+: ask LLM to generate improved parameter values
            param_set, prompt_text, response_text = _generate_config_with_llm(
                requirements=requirements,
                env=env,
                iteration=iteration,
                current_config_params=current_config_params,
                previous_results=session.get_latest_results(),
                previous_eval=_get_previous_eval(session),
                past_iterations=list(session.iterations),
                last_benchmark_error=last_benchmark_error,
                pipeline_topology=last_pipeline_topology,
            )
            # Save the LLM conversation (prompt + response) to a human-readable file
            _save_llm_conversation(
                session_dir=session_dir,
                iteration=iteration,
                prompt_text=prompt_text,
                response_text=response_text,
            )

            # Apply set/delete operations to the accumulated params dict
            # 1. Delete params (revert to template defaults)
            for param_name in param_set.delete_params:
                if param_name in current_config_params:
                    del current_config_params[param_name]
                    logger.info(f"Deleted param (reverted to default): {param_name}")
            params_deleted_this_epoch = list(param_set.delete_params)

            # 2. Set/override params
            current_config_params.update(param_set.parameters)
            params_set_this_epoch = dict(param_set.parameters)

            # Generate the FastDDS XML config from the accumulated parameters
            generate_fastdds_config(
                DDSParameterSet(parameters=current_config_params),
                config_path,
            )
            llm_reasoning = param_set.reasoning

        # -------------------------------------------------------------------
        # Step 2: Run benchmark (topology collected in background thread)
        # -------------------------------------------------------------------
        epoch_dir = get_epoch_dir(session_dir, iteration)
        logger.info(f"Running benchmark with config: {config_path}")
        try:
            result_json_path, pipeline_topology = run_benchmark(
                benchmark_config=requirements.benchmark,
                fastdds_config_path=config_path,
                epoch_dir=epoch_dir,
                iteration=iteration,
            )
            last_pipeline_topology = pipeline_topology
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Benchmark failed: {error_msg}")
            _record_failed_iteration(
                session, iteration, config_path, llm_reasoning, error_msg,
                params_set_this_epoch, params_deleted_this_epoch,
            )
            last_benchmark_error = error_msg
            consecutive_failures += 1
            _save_session_state(session, session_dir)
            if consecutive_failures >= 3:
                logger.error(
                    f"Benchmark failed {consecutive_failures} consecutive times "
                    f"('{error_msg}'). Stopping optimization early."
                )
                break
            continue

        # Update env with real pipeline topology from the first successful
        # benchmark run. In benchmark mode the nodes aren't running before
        # the benchmark starts, so active_nodes/active_topics are empty at
        # collection time. We backfill them here so the LLM gets accurate
        # context from epoch 2 onward.
        if pipeline_topology and not env.active_nodes:
            env.active_nodes = list(pipeline_topology.nodes)
            env.active_topics = [
                TopicInfo(
                    name=tc.name,
                    msg_type=tc.msg_type,
                    publisher_count=len(tc.publishers),
                    subscriber_count=len(tc.subscribers),
                )
                for tc in pipeline_topology.topics
            ]
            logger.info(
                f"Environment updated from benchmark topology: "
                f"{len(env.active_nodes)} nodes, {len(env.active_topics)} topics"
            )

        # -------------------------------------------------------------------
        # Step 3: Parse and evaluate results
        # -------------------------------------------------------------------
        results = parse_benchmark_results(result_json_path)
        eval_result = evaluate_results(results, requirements.performance_requirements)

        # -------------------------------------------------------------------
        # Step 4: Record iteration
        # -------------------------------------------------------------------
        opt_iteration = OptimizationIteration(
            iteration_number=iteration,
            config_path=str(config_path),
            results=results,
            requirements_met=eval_result.all_metrics_met,
            required_metrics_met=eval_result.required_metrics_met,
            optional_metrics_met=eval_result.optional_metrics_met,
            performance_score=eval_result.performance_score,
            llm_reasoning=llm_reasoning,
            pipeline_topology=pipeline_topology,
            params_set=params_set_this_epoch,
            params_deleted=params_deleted_this_epoch,
        )
        session.iterations.append(opt_iteration)

        best = session.get_best_iteration()
        if best:
            session.best_iteration = session.iterations.index(best)

        _save_session_state(session, session_dir)

        consecutive_failures = 0
        last_benchmark_error = None

        # -------------------------------------------------------------------
        # Step 5: Termination conditions
        # -------------------------------------------------------------------

        # SUCCESS: all metrics (required + optional) met → stop immediately
        if eval_result.all_metrics_met:
            logger.info(
                f"\n✓ All metrics (required + optional) met at epoch {iteration}! "
                "Stopping optimization."
            )
            session.success = True
            break

        if eval_result.required_metrics_met:
            logger.info(
                f"✓ All REQUIRED metrics met at epoch {iteration}. "
                "Continuing to optimize optional metrics..."
            )

        # Convergence check: only when required metrics are already met.
        # (never stop early if requirements not satisfied)
        # NOTE: the success break above now only fires on all_metrics_met,
        # so this block is reachable when required_metrics_met=True but
        # optional metrics have not yet been fully optimized.
        if (iteration > 1
                and eval_result.required_metrics_met
                and check_convergence(
                    current_score=eval_result.performance_score,
                    previous_score=previous_score,
                    threshold=convergence_threshold,
                )):
            logger.info(
                f"Optimization converged at epoch {iteration} "
                f"(improvement < {convergence_threshold * 100:.1f}%). "
                "Stopping early."
            )
            session.success = True
            session.converged = True
            break

        previous_score = eval_result.performance_score

        if iteration == max_iterations:
            logger.warning(
                f"Reached maximum epochs ({max_iterations}). "
                "Saving best configuration found."
            )

    return session


def _generate_config_with_llm(
    requirements: RequirementsConfig,
    env: EnvironmentInfo,
    iteration: int,
    current_config_params: dict,
    previous_results,
    previous_eval,
    past_iterations: list,
    last_benchmark_error: Optional[str] = None,
    pipeline_topology: Optional[PipelineTopology] = None,
) -> tuple:
    """
    Generate improved FastDDS parameter values using the LLM.

    Builds a feedback prompt with the current parameter values, benchmark results,
    performance gaps, pipeline topology, and a history of past epochs (last 2 in
    full detail, older as one-line summaries). Retries up to MAX_LLM_PARSE_RETRIES
    times if the response cannot be parsed.

    Returns:
        Tuple of (DDSParameterSet, prompt_text, response_text).
        - DDSParameterSet has parameters dict, delete_params list, and reasoning.
        - prompt_text is the full prompt sent to the LLM (for logging).
        - response_text is the raw LLM response (for logging).
    """
    last_prompt = ""
    last_response = ""

    for attempt in range(1, MAX_LLM_PARSE_RETRIES + 1):
        try:
            logger.info(f"Generating improved FastDDS params via LLM (attempt {attempt})...")

            # Compute performance gaps when we have actual benchmark results
            if previous_eval is not None and previous_results is not None:
                gaps = build_performance_gaps(
                    eval_result=previous_eval,
                    results=previous_results,
                    requirements=requirements.performance_requirements,
                )
            else:
                gaps = {}  # no data — benchmark failed last time

            prompt = build_feedback_prompt(
                requirements=requirements,
                env=env,
                current_config_params=current_config_params,
                results=previous_results,
                performance_gaps=gaps,
                iteration=iteration,
                past_iterations=past_iterations,
                benchmark_error=last_benchmark_error,
                pipeline_topology=pipeline_topology,
            )
            last_prompt = prompt

            response_text = call_llm(prompt, requirements.llm_config)
            last_response = response_text

            param_set = parse_llm_response(response_text)
            logger.info(
                f"LLM generated {len(param_set.parameters)} FastDDS parameters "
                f"(set: {list(param_set.parameters.keys())}, "
                f"delete: {param_set.delete_params}). "
                f"Reasoning: {(param_set.reasoning or 'N/A')[:100]}..."
            )
            return param_set, prompt, response_text

        except ValueError as e:
            logger.warning(
                f"Failed to parse LLM response (attempt {attempt}/{MAX_LLM_PARSE_RETRIES}): {e}"
            )
            if attempt == MAX_LLM_PARSE_RETRIES:
                raise RuntimeError(
                    f"LLM response parsing failed after {MAX_LLM_PARSE_RETRIES} attempts: {e}"
                ) from e

    raise RuntimeError("LLM config generation failed unexpectedly")


def _save_llm_conversation(
    session_dir: Path,
    iteration: int,
    prompt_text: str,
    response_text: str,
) -> None:
    """
    Save the full LLM conversation (prompt + response) to a human-readable Markdown file.

    The file is saved as epoch_N/llm_conversation.md and contains:
    - The complete prompt sent to the LLM
    - The complete raw response from the LLM

    Note: The extracted parameters are NOT included here — they are part of the
    LLM response itself and are visible in the response section.

    Args:
        session_dir: Session directory path.
        iteration: Epoch number (1-based).
        prompt_text: The full prompt string sent to the LLM.
        response_text: The raw response string from the LLM.
    """
    conversation_path = get_conversation_path(session_dir, iteration)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# LLM Conversation — Epoch {iteration}

**Timestamp:** {timestamp}

---

## 📤 Prompt (sent to LLM)

```
{prompt_text}
```

---

## 📥 Response (from LLM)

{response_text}
"""

    try:
        conversation_path.write_text(content, encoding="utf-8")
        logger.info(f"LLM conversation saved to: {conversation_path}")
    except Exception as e:
        logger.warning(f"Failed to save LLM conversation: {e}")


def _get_previous_eval(session: OptimizationSession):
    """Get the evaluation result from the last successful iteration."""
    if not session.iterations:
        return None
    last_iter = session.iterations[-1]
    if last_iter.results is None:
        return None
    if session.requirements:
        return evaluate_results(last_iter.results, session.requirements.performance_requirements)
    return None


def _record_failed_iteration(
    session: OptimizationSession,
    iteration: int,
    config_path: Path,
    llm_reasoning: str,
    error_msg: str,
    params_set: dict,
    params_deleted: list,
) -> None:
    """Record a failed iteration (benchmark error)."""
    opt_iteration = OptimizationIteration(
        iteration_number=iteration,
        config_path=str(config_path),
        results=None,
        requirements_met=False,
        required_metrics_met=False,
        optional_metrics_met=False,
        performance_score=0.0,
        llm_reasoning=llm_reasoning,
        benchmark_error=error_msg,
        params_set=params_set,
        params_deleted=params_deleted,
    )
    session.iterations.append(opt_iteration)


def _save_session_state(session: OptimizationSession, session_dir: Path) -> None:
    """Save the current session state to session_summary.json."""
    summary_path = get_session_summary_path(session_dir)
    try:
        state_data = json.loads(session.model_dump_json())
        write_json_atomic(summary_path, state_data)
    except Exception as e:
        logger.warning(f"Failed to save session state: {e}")


def _print_optimization_summary(
    session: OptimizationSession,
    requirements: RequirementsConfig,
) -> None:
    """
    Print a highlighted per-requirement summary of the optimization results.

    Shows:
    - Overall result (SUCCESS / BEST EFFORT) in a prominent box
    - Per-requirement table: target vs actual vs status
    - Location of the best config file
    """
    W = 64  # box width

    # -----------------------------------------------------------------------
    # Overall result banner
    # -----------------------------------------------------------------------
    if session.success:
        banner_text = "OPTIMIZATION RESULT:  ✓  ALL REQUIREMENTS MET"
        banner_border = "═" * W
        banner = (
            f"\n╔{banner_border}╗\n"
            f"║  {banner_text:<{W-2}}║\n"
            f"╚{banner_border}╝"
        )
    else:
        banner_text = "OPTIMIZATION RESULT:  ⚠  REQUIREMENTS NOT FULLY MET"
        banner_border = "═" * W
        banner = (
            f"\n╔{banner_border}╗\n"
            f"║  {banner_text:<{W-2}}║\n"
            f"╚{banner_border}╝"
        )

    lines = [banner]

    # -----------------------------------------------------------------------
    # Session stats
    # -----------------------------------------------------------------------
    lines.append(f"\n  Session:    {session.session_id}")
    lines.append(f"  Epochs:     {len(session.iterations)}")
    if session.converged:
        lines.append("  Stopped:    converged (no further improvement)")
    elif session.success:
        lines.append("  Stopped:    requirements met ✓")
    else:
        lines.append("  Stopped:    max epochs reached")

    # -----------------------------------------------------------------------
    # Per-requirement table (from best iteration)
    # -----------------------------------------------------------------------
    best = session.get_best_iteration()
    if best and best.results:
        # Re-evaluate to get metric_status breakdown
        eval_result = evaluate_results(best.results, requirements.performance_requirements)

        lines.append(f"\n  {'Requirement':<28} {'Target':<14} {'Actual':<14} {'Status'}")
        lines.append(f"  {'-'*28} {'-'*14} {'-'*14} {'-'*10}")

        # Human-readable metric labels
        _LABELS = {
            "latency_mean_ms":        ("Mean Latency",    "ms",    ""),
            "latency_p95_ms":         ("P95 Latency",     "ms",    ""),
            "latency_p99_ms":         ("P99 Latency",     "ms",    ""),
            "throughput_msgs_per_sec":("Throughput",      "msg/s", ""),
            "packet_loss_rate":       ("Packet Loss",     "%",     "×100"),
            "cpu_percent":            ("CPU Usage",       "%",     ""),
            "memory_mb":              ("Memory",          "MB",    ""),
        }

        for metric_name, status in eval_result.metric_status.items():
            label, unit, transform = _LABELS.get(metric_name, (metric_name, "", ""))
            opt_tag = " (opt)" if status["optional"] else ""
            label_str = f"{label}{opt_tag}"

            actual_val = status["actual"]
            target_val = status["target"]
            op = status["operator"]

            # Apply transform for display (packet_loss_rate → %)
            if transform == "×100":
                actual_disp = f"{actual_val * 100:.4f}{unit}"
                target_disp = f"{op}{target_val * 100:.4f}{unit}"
            else:
                actual_disp = f"{actual_val:.2f}{unit}"
                target_disp = f"{op}{target_val:.2f}{unit}"

            status_str = "✓ MET" if status["met"] else "✗ NOT MET"
            lines.append(
                f"  {label_str:<28} {target_disp:<14} {actual_disp:<14} {status_str}"
            )

        lines.append(f"\n  Best score: {best.performance_score:.1%}  "
                     f"(epoch {best.iteration_number})")

    # -----------------------------------------------------------------------
    # Best config location
    # -----------------------------------------------------------------------
    if session.final_config_path:
        lines.append(f"\n  Best config: {session.final_config_path}")
        lines.append(
            f"\n  To use:\n"
            f"    export FASTRTPS_DEFAULT_PROFILES_FILE={session.final_config_path}"
        )

    lines.append("\n" + "=" * (W + 2))
    logger.info("\n".join(lines))
