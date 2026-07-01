# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Optimizer module: the main optimization loop that ties all components together.

Components:
- optimization_loop: Orchestrates the full optimization workflow
- evaluator: Evaluates benchmark results against requirements
- feedback_builder: Builds performance gap descriptions for LLM feedback
"""
