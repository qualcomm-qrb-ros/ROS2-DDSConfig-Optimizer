# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for the LLM client."""

import pytest
from unittest.mock import MagicMock, patch

from dds_optimizer.models import LLMConfig


def make_openai_llm_config():
    """Create an LLMConfig for OpenAI provider."""
    return LLMConfig(provider="openai", model="gpt-4o", api_key_env="TEST_API_KEY")


def make_mock_openai_response(content="test response", choices_count=1):
    """Create a mock OpenAI API response."""
    response = MagicMock()
    if choices_count == 0:
        response.choices = []
    else:
        choice = MagicMock()
        choice.message.content = content
        response.choices = [choice] * choices_count
    response.usage.total_tokens = 100
    return response


# Custom exception classes that are distinct from IndexError
# to prevent the `except RateLimitError/APIConnectionError/APIError` clauses
# from accidentally catching IndexError during testing.
class _MockRateLimitError(Exception):
    pass


class _MockAPIConnectionError(Exception):
    pass


class _MockAPIError(Exception):
    pass


def _make_openai_module_mock(client):
    """Build a mock openai module with specific exception classes."""
    mock_mod = MagicMock()
    mock_mod.OpenAI.return_value = client
    mock_mod.RateLimitError = _MockRateLimitError
    mock_mod.APIConnectionError = _MockAPIConnectionError
    mock_mod.APIError = _MockAPIError
    return mock_mod


# -----------------------------------------------------------------------
# Test _call_openai - empty choices guard
# -----------------------------------------------------------------------


def test_bug_openai_empty_choices_raises_index_error():
    """
    BUG: _call_openai accesses response.choices[0] without checking if
    choices is empty (llm_client.py:288).

    When the OpenAI API (or a compatible proxy) returns a 200 OK response
    with an empty choices list, the code raises a cryptic IndexError instead
    of a meaningful RuntimeError.

    EXPECTED (after fix):
    A RuntimeError with 'empty response' should be raised when choices is empty.

    CURRENT (buggy):
    An IndexError propagates: 'list index out of range'.
    """
    from dds_optimizer.llm.llm_client import _call_openai

    llm_config = make_openai_llm_config()
    empty_choices_response = make_mock_openai_response(choices_count=0)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = empty_choices_response
    mock_mod = _make_openai_module_mock(mock_client)

    with patch.dict("sys.modules", {"openai": mock_mod}):
        with patch.dict("os.environ", {"TEST_API_KEY": "sk-test"}):
            # After fix: raises RuntimeError with clear "empty response" message.
            # With bug: raises IndexError ('list index out of range') which
            #           does NOT match RuntimeError → this assertion fails.
            with pytest.raises(RuntimeError, match="empty response"):
                _call_openai(
                    prompt="test prompt",
                    llm_config=llm_config,
                    api_key="sk-test",
                )


def test_openai_normal_response_returns_content():
    """Test that a normal OpenAI response with content is returned correctly."""
    from dds_optimizer.llm.llm_client import _call_openai

    llm_config = make_openai_llm_config()
    normal_response = make_mock_openai_response(content="Generated config JSON")

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = normal_response
    mock_mod = _make_openai_module_mock(mock_client)

    with patch.dict("sys.modules", {"openai": mock_mod}):
        with patch.dict("os.environ", {"TEST_API_KEY": "sk-test"}):
            result = _call_openai(
                prompt="test prompt",
                llm_config=llm_config,
                api_key="sk-test",
            )

    assert result == "Generated config JSON"

