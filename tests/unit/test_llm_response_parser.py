# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for the LLM response parser (structured JSON set/delete format)."""

import pytest

from dds_optimizer.llm.response_parser import (
    _extract_json_from_response,
    _extract_reasoning,
    _normalize_params,
    parse_llm_response,
)

# Sample structured JSON (new format)
SAMPLE_STRUCTURED_STR = '{"set": {"intraprocess_delivery": "FULL", "reliability_kind": "BEST_EFFORT", "history_depth": 1}, "delete": ["udp_send_buffer_size"]}'

# Sample flat JSON (legacy format)
SAMPLE_FLAT_STR = '{"intraprocess_delivery": "FULL", "reliability_kind": "BEST_EFFORT", "history_depth": 1}'

# Sample with only "set"
SAMPLE_SET_ONLY_STR = '{"set": {"history_depth": 10, "reliability_kind": "RELIABLE"}}'

# Sample with only "delete"
SAMPLE_DELETE_ONLY_STR = '{"delete": ["udp_send_buffer_size"]}'


# -----------------------------------------------------------------------
# Test _extract_json_from_response
# -----------------------------------------------------------------------

def test_extract_json_from_json_code_block():
    response = f"```json\n{SAMPLE_STRUCTURED_STR}\n```"
    result = _extract_json_from_response(response)
    assert result is not None
    assert "set" in result
    assert result["set"]["intraprocess_delivery"] == "FULL"
    assert result["delete"] == ["udp_send_buffer_size"]


def test_extract_json_from_generic_code_block():
    response = f"```\n{SAMPLE_STRUCTURED_STR}\n```"
    result = _extract_json_from_response(response)
    assert result is not None
    assert "set" in result


def test_extract_json_from_raw_json():
    response = f"Here are the parameters:\n{SAMPLE_STRUCTURED_STR}\nEnd."
    result = _extract_json_from_response(response)
    assert result is not None
    assert result["set"]["history_depth"] == 1


def test_extract_json_returns_none_for_no_json():
    result = _extract_json_from_response("This is just plain text with no JSON.")
    assert result is None


def test_extract_json_returns_none_for_xml():
    result = _extract_json_from_response("```xml\n<dds><profiles/></dds>\n```")
    assert result is None


def test_extract_json_with_surrounding_text():
    response = f"I analyzed the requirements:\n\n```json\n{SAMPLE_STRUCTURED_STR}\n```\n\nThis should improve performance."
    result = _extract_json_from_response(response)
    assert result is not None
    assert result["set"]["intraprocess_delivery"] == "FULL"


def test_extract_json_single_param():
    response = '```json\n{"set": {"history_depth": 10}}\n```'
    result = _extract_json_from_response(response)
    assert result == {"set": {"history_depth": 10}}


def test_extract_json_all_types():
    response = '```json\n{"set": {"reliability_kind": "RELIABLE", "history_depth": 5, "udp_non_blocking_send": true}}\n```'
    result = _extract_json_from_response(response)
    assert result["set"]["reliability_kind"] == "RELIABLE"
    assert result["set"]["history_depth"] == 5
    assert result["set"]["udp_non_blocking_send"] is True


# -----------------------------------------------------------------------
# Test _normalize_params
# -----------------------------------------------------------------------

def test_normalize_structured_format():
    raw = {"set": {"history_depth": 10, "reliability_kind": "RELIABLE"}, "delete": ["udp_send_buffer_size"]}
    set_params, delete_params = _normalize_params(raw)
    assert set_params == {"history_depth": 10, "reliability_kind": "RELIABLE"}
    assert delete_params == ["udp_send_buffer_size"]


def test_normalize_set_only():
    raw = {"set": {"history_depth": 5}}
    set_params, delete_params = _normalize_params(raw)
    assert set_params == {"history_depth": 5}
    assert delete_params == []


def test_normalize_delete_only():
    raw = {"delete": ["udp_send_buffer_size"]}
    set_params, delete_params = _normalize_params(raw)
    assert set_params == {}
    assert delete_params == ["udp_send_buffer_size"]


def test_normalize_legacy_flat_format():
    raw = {"history_depth": 10, "reliability_kind": "RELIABLE"}
    set_params, delete_params = _normalize_params(raw)
    assert set_params == {"history_depth": 10, "reliability_kind": "RELIABLE"}
    assert delete_params == []


def test_normalize_filters_non_string_delete_entries():
    raw = {"set": {}, "delete": ["valid_param", 123, None, "another_param"]}
    set_params, delete_params = _normalize_params(raw)
    assert delete_params == ["valid_param", "another_param"]


# -----------------------------------------------------------------------
# Test _extract_reasoning
# -----------------------------------------------------------------------

def test_extract_reasoning_from_reasoning_line():
    response = f"Reasoning: Tuning buffers for low latency.\n\n```json\n{SAMPLE_STRUCTURED_STR}\n```"
    result = _extract_reasoning(response)
    assert "Tuning buffers" in result


def test_extract_reasoning_from_hash_reasoning():
    response = f"# Reasoning: Increased history depth.\n```json\n{SAMPLE_STRUCTURED_STR}\n```"
    result = _extract_reasoning(response)
    assert "Increased history depth" in result


def test_extract_reasoning_from_text_before_block():
    response = f"This is my reasoning paragraph.\n\n```json\n{SAMPLE_STRUCTURED_STR}\n```"
    result = _extract_reasoning(response)
    assert "reasoning paragraph" in result


def test_extract_reasoning_empty_when_no_text():
    response = f"```json\n{SAMPLE_STRUCTURED_STR}\n```"
    result = _extract_reasoning(response)
    assert result == ""


# -----------------------------------------------------------------------
# Test parse_llm_response — structured format
# -----------------------------------------------------------------------

def test_parse_structured_response():
    response = f"Reasoning: Using SHM transport for low latency.\n\n```json\n{SAMPLE_STRUCTURED_STR}\n```"
    param_set = parse_llm_response(response)
    assert param_set.parameters["intraprocess_delivery"] == "FULL"
    assert param_set.delete_params == ["udp_send_buffer_size"]
    assert "SHM transport" in param_set.reasoning


def test_parse_set_only_response():
    response = f"Reasoning: Only setting params.\n```json\n{SAMPLE_SET_ONLY_STR}\n```"
    param_set = parse_llm_response(response)
    assert param_set.parameters == {"history_depth": 10, "reliability_kind": "RELIABLE"}
    assert param_set.delete_params == []


def test_parse_delete_only_response():
    response = f"Reasoning: Reverting bad param.\n```json\n{SAMPLE_DELETE_ONLY_STR}\n```"
    param_set = parse_llm_response(response)
    assert param_set.parameters == {}
    assert param_set.delete_params == ["udp_send_buffer_size"]


def test_parse_legacy_flat_response():
    """Legacy flat format is still accepted for backward compatibility."""
    response = f"Reasoning: Legacy format.\n```json\n{SAMPLE_FLAT_STR}\n```"
    param_set = parse_llm_response(response)
    assert param_set.parameters["intraprocess_delivery"] == "FULL"
    assert param_set.delete_params == []


def test_parse_response_without_reasoning():
    response = f"```json\n{SAMPLE_STRUCTURED_STR}\n```"
    param_set = parse_llm_response(response)
    assert len(param_set.parameters) > 0
    assert param_set.reasoning == ""


def test_parse_response_raises_on_no_json():
    with pytest.raises(ValueError, match="Could not extract FastDDS parameters"):
        parse_llm_response("This response has no JSON at all.")


def test_parse_response_raises_on_xml_only():
    with pytest.raises(ValueError, match="Could not extract FastDDS parameters"):
        parse_llm_response("```xml\n<dds><profiles/></dds>\n```")


def test_parse_response_reasoning_extracted():
    response = f"Reasoning: Reduced heartbeat period to 100ms.\n```json\n{SAMPLE_STRUCTURED_STR}\n```"
    param_set = parse_llm_response(response)
    assert "100ms" in param_set.reasoning


def test_parse_response_empty_set_and_delete():
    """Empty set and delete is valid (no-op)."""
    response = '```json\n{"set": {}, "delete": []}\n```'
    param_set = parse_llm_response(response)
    assert param_set.parameters == {}
    assert param_set.delete_params == []


def test_parse_response_multiple_deletes():
    response = '```json\n{"set": {"history_depth": 5}, "delete": ["udp_send_buffer_size", "shm_max_message_size", "udp_receive_buffer_size"]}\n```'
    param_set = parse_llm_response(response)
    assert param_set.parameters == {"history_depth": 5}
    assert len(param_set.delete_params) == 3
    assert "udp_send_buffer_size" in param_set.delete_params
