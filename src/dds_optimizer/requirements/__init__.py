# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Requirements module: parses and validates user_requirements.xml.

This module is responsible for reading the user-provided XML file that specifies:
- The benchmark test file path and launch command
- Performance targets (latency, throughput, reliability, CPU, memory)
- Optimization loop settings (max iterations, convergence threshold)
- LLM API configuration (provider, model, base URL, API key env var)
"""
