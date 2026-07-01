# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Config module: generates, validates, and deploys FastDDS XML configuration files.

Components:
- generator: Fills the XML template with LLM-suggested parameter values
- validator: Validates the generated XML for structural correctness
- deployer: Sets FASTRTPS_DEFAULT_PROFILES_FILE environment variable
- templates/: XML template with performance-critical parameter placeholders
"""
