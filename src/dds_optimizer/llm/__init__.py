# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
LLM module: interfaces with Large Language Models to generate FastDDS configurations.

Components:
- prompt_builder: Constructs structured prompts with environment info and requirements
- llm_client: Handles API calls to OpenAI/Anthropic with retry logic
- response_parser: Extracts and validates parameter values from LLM responses
"""
