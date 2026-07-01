# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Response Parser: extracts FastDDS parameter key-value pairs from LLM responses.

The LLM is instructed to return a structured JSON object with two keys:
- "set":    dict of parameter name → value to apply
- "delete": list of parameter names to revert to system defaults

Wrapped in a markdown code block, with optional reasoning before it:

    Reasoning: <explanation paragraph>

    ```json
    {
      "set": {
        "intraprocess_delivery": "FULL",
        "reliability_kind": "BEST_EFFORT",
        "history_depth": 1
      },
      "delete": ["udp_send_buffer_size"]
    }
    ```

This module handles:
1. Extracting JSON from ```json ... ``` or ``` ... ``` code blocks
2. Falling back to raw JSON object detection if no code block is found
3. Normalizing both the new {"set": ..., "delete": ...} format and the
   legacy flat-dict format (for backward compatibility)
4. Extracting optional reasoning text
5. Returning a DDSParameterSet with parameters dict, delete_params list, and reasoning

Using JSON params instead of full XML avoids FastDDS [XMLPARSER Error] issues
that occur when the LLM generates malformed or incomplete XML.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..models import DDSParameterSet
from ..utils.logger import get_logger

logger = get_logger(__name__)


def _extract_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Extract a JSON object from an LLM response.

    Tries in order:
    1. ```json ... ``` markdown code block
    2. ``` ... ``` generic code block (if content parses as JSON object)
    3. Raw JSON object starting with { in the response

    Args:
        response_text: Raw text response from the LLM.

    Returns:
        Parsed JSON dict, or None if no valid JSON object could be found.
    """
    # Try ```json ... ``` block first
    json_block = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
    match = json_block.search(response_text)
    if match:
        candidate = match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try generic ``` ... ``` block
    code_block = re.compile(r"```\s*(.*?)\s*```", re.DOTALL)
    match = code_block.search(response_text)
    if match:
        candidate = match.group(1).strip()
        if candidate.startswith("{"):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    # Try to find a raw JSON object in the response
    # Look for the first { and try to parse from there
    brace_idx = response_text.find("{")
    if brace_idx != -1:
        # Find the matching closing brace
        depth = 0
        for i, ch in enumerate(response_text[brace_idx:], start=brace_idx):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = response_text[brace_idx : i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    return None


def _normalize_params(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Normalize the extracted JSON into (set_params, delete_params).

    Handles two formats:
    1. New structured format:
       {"set": {"param": value, ...}, "delete": ["param", ...]}
    2. Legacy flat format (backward compatibility):
       {"param": value, ...}

    Args:
        raw: The raw parsed JSON dict from the LLM response.

    Returns:
        Tuple of (set_params dict, delete_params list).
    """
    # New structured format: has "set" key with a dict value
    if "set" in raw and isinstance(raw["set"], dict):
        set_params = raw["set"]
        delete_params = raw.get("delete", [])
        if not isinstance(delete_params, list):
            delete_params = []
        # Filter: only keep string entries in delete list
        delete_params = [p for p in delete_params if isinstance(p, str)]
        return set_params, delete_params

    # Legacy flat format: all keys are parameter names
    # (no "set" key, or "set" is not a dict)
    # Exclude any "delete" key if present
    set_params = {k: v for k, v in raw.items() if k != "delete"}
    delete_params = raw.get("delete", [])
    if isinstance(delete_params, list):
        delete_params = [p for p in delete_params if isinstance(p, str)]
    else:
        delete_params = []
    return set_params, delete_params


def _extract_reasoning(response_text: str) -> str:
    """
    Extract reasoning text from the LLM response.

    Looks for a line starting with 'Reasoning:' or '# Reasoning:',
    or any text before the first code block.

    Args:
        response_text: Raw text response from the LLM.

    Returns:
        Reasoning string, or empty string if not found.
    """
    # Look for explicit "# Reasoning:" or "Reasoning:" line
    reasoning_pattern = re.compile(
        r"(?:^|\n)#?\s*[Rr]easoning\s*:?\s*(.*?)(?=\n```|\Z)",
        re.DOTALL,
    )
    match = reasoning_pattern.search(response_text)
    if match:
        return match.group(1).strip()

    # Fall back: any text before the first ``` block
    code_start = response_text.find("```")
    if code_start > 0:
        before = response_text[:code_start].strip()
        if before:
            return before

    return ""


def parse_llm_response(response_text: str) -> DDSParameterSet:
    """
    Parse an LLM response and extract FastDDS parameter key-value pairs.

    The LLM is expected to return a structured JSON object:
        {
          "set": {"param_name": value, ...},
          "delete": ["param_name", ...]
        }

    Both "set" and "delete" are optional. The legacy flat-dict format is
    also accepted for backward compatibility.

    Args:
        response_text: Raw text response from the LLM.

    Returns:
        DDSParameterSet with parameters dict, delete_params list, and reasoning.

    Raises:
        ValueError: If no valid JSON object could be extracted.

    Example:
        >>> response = '''Reasoning: Enable intraprocess delivery.
        ... ```json
        ... {"set": {"intraprocess_delivery": "FULL"}, "delete": ["udp_send_buffer_size"]}
        ... ```'''
        >>> param_set = parse_llm_response(response)
        >>> print(param_set.parameters)
        {'intraprocess_delivery': 'FULL'}
        >>> print(param_set.delete_params)
        ['udp_send_buffer_size']
    """
    raw = _extract_json_from_response(response_text)
    if raw is None:
        raise ValueError(
            "Could not extract FastDDS parameters from LLM response. "
            "The response did not contain a valid JSON object. "
            f"Response preview: {response_text[:300]}..."
        )

    set_params, delete_params = _normalize_params(raw)
    reasoning = _extract_reasoning(response_text)

    logger.info(
        f"Extracted {len(set_params)} FastDDS parameters from LLM response: "
        f"{list(set_params.keys())}"
    )
    if delete_params:
        logger.info(f"Parameters to delete (revert to defaults): {delete_params}")
    if reasoning:
        logger.debug(f"LLM reasoning: {reasoning[:200]}")

    return DDSParameterSet(
        parameters=set_params,
        delete_params=delete_params,
        reasoning=reasoning,
    )
