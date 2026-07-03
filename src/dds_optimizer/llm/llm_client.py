# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
LLM Client: handles API calls to OpenAI, Anthropic, OpenRouter, and custom plugins.

Supports:
- OpenRouter API (free and paid models via https://openrouter.ai/api/v1)
- OpenAI API (and compatible endpoints via base_url, e.g., Azure OpenAI, local LLMs)
- Anthropic API (Claude models)
- Custom plugin providers (via plugin_module)

Features:
- Automatic retry with exponential backoff on transient errors
- Configurable timeout
- Unified interface regardless of provider
"""

import os
import time
from typing import Optional

from ..models import LLMConfig
from ..utils.logger import get_logger

logger = get_logger(__name__)

# Maximum number of retry attempts on transient API errors
MAX_RETRIES = 3

# Base delay in seconds for exponential backoff (doubles each retry)
RETRY_BASE_DELAY = 2.0

# Maximum tokens in the LLM response
MAX_RESPONSE_TOKENS = 4096


def call_llm(prompt: str, llm_config: LLMConfig) -> str:
    """
    Send a prompt to the configured LLM and return the response text.

    This is the main entry point for LLM API calls. It handles provider
    selection, API key retrieval, and retry logic automatically.

    Args:
        prompt: The complete prompt string to send to the LLM.
        llm_config: LLM configuration (provider, model, base_url, api_key_env).

    Returns:
        The LLM's response text as a string.

    Raises:
        ValueError: If the API key environment variable is not set.
        RuntimeError: If all retry attempts fail.

    Example:
        >>> from dds_optimizer.models import LLMConfig
        >>> config = LLMConfig(provider="openai", model="gpt-4", api_key_env="OPENAI_API_KEY")
        >>> response = call_llm("Generate a FastDDS config...", config)
        >>> print(response[:100])
    """
    # Retrieve API key from environment
    api_key = os.environ.get(llm_config.api_key_env)
    if not api_key:
        raise ValueError(
            f"LLM API key not found in environment variable '{llm_config.api_key_env}'. "
            f"Please set it with: export {llm_config.api_key_env}=<your-api-key>"
        )

    provider = llm_config.provider.lower()

    # If a plugin module is specified, use it regardless of provider field
    if llm_config.plugin_module:
        return _call_plugin_provider(prompt, llm_config, api_key)
    elif provider == "openrouter":
        return _call_openrouter(prompt, llm_config, api_key)
    elif provider == "openai":
        return _call_openai(prompt, llm_config, api_key)
    elif provider == "anthropic":
        return _call_anthropic(prompt, llm_config, api_key)
    elif provider == "plugin":
        raise ValueError(
            "provider='plugin' requires plugin_module to be set in llm_config."
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider: '{provider}'. "
            "Use 'openrouter', 'openai', or 'anthropic'."
        )


def _call_openrouter(prompt: str, llm_config: LLMConfig, api_key: str) -> str:
    """
    Call the OpenRouter API using direct HTTP requests.

    Uses the requests library instead of the OpenAI client to correctly handle
    reasoning models (e.g. openrouter/free → DeepSeek R1) which return
    content=null and put the actual output in reasoning_details.

    Sends {"reasoning": {"enabled": true}} to enable chain-of-thought reasoning.
    If the response content is empty, falls back to extracting text from
    reasoning_details.

    See https://openrouter.ai/models for available models.

    Args:
        prompt: The prompt to send.
        llm_config: LLM configuration (model, api_key_env, optional base_url override).
        api_key: The OpenRouter API key (from LLM_API_KEY env var).

    Returns:
        Response text from the model.
    """
    try:
        import requests as req
    except ImportError:
        raise ImportError(
            "requests package is required. Install with: pip install requests"
        )

    base_url = llm_config.base_url or "https://openrouter.ai/api/v1"
    url = base_url.rstrip("/") + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": llm_config.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_RESPONSE_TOKENS,
        "reasoning": {"enabled": True},
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                f"Calling OpenRouter API (model={llm_config.model}, "
                f"attempt={attempt}/{MAX_RETRIES})"
            )

            resp = req.post(url, headers=headers, json=payload, timeout=120)

            # Handle rate limit (429) with backoff
            if resp.status_code == 429:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"OpenRouter rate limit (attempt {attempt}/{MAX_RETRIES}). "
                    f"Waiting {delay:.1f}s before retry..."
                )
                last_error = RuntimeError("Rate limit: HTTP 429")
                time.sleep(delay)
                continue

            # Fail immediately on 4xx client errors (except 429)
            if 400 <= resp.status_code < 500:
                raise RuntimeError(
                    f"OpenRouter API client error: HTTP {resp.status_code} — {resp.text}"
                )

            # Retry on 5xx server errors
            if resp.status_code >= 500:
                delay = RETRY_BASE_DELAY * attempt
                logger.warning(
                    f"OpenRouter server error HTTP {resp.status_code} "
                    f"(attempt {attempt}/{MAX_RETRIES}). "
                    f"Waiting {delay:.1f}s before retry..."
                )
                last_error = RuntimeError(f"Server error: HTTP {resp.status_code}")
                time.sleep(delay)
                continue

            data = resp.json()
            message = data["choices"][0]["message"]

            # Primary: use content field
            content = message.get("content") or ""

            # Fallback: extract text from reasoning_details when content is empty.
            # Reasoning models (e.g. DeepSeek R1 via openrouter/free) return
            # content=null and put the actual output in reasoning_details.
            if not content.strip():
                reasoning_details = message.get("reasoning_details") or []
                parts = []
                for item in reasoning_details:
                    # Items have type "thinking" or "text"; extract whichever has text
                    text = item.get("thinking") or item.get("text") or ""
                    if text:
                        parts.append(text)
                content = "\n".join(parts)

            if not content.strip():
                raise RuntimeError("LLM returned empty response")

            usage = data.get("usage", {})
            total_tokens = usage.get("total_tokens", "unknown")
            logger.info(
                f"OpenRouter API call successful (tokens: {total_tokens})"
            )
            return content

        except req.exceptions.ConnectionError as e:
            delay = RETRY_BASE_DELAY * attempt
            logger.warning(
                f"OpenRouter connection error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                f"Waiting {delay:.1f}s before retry..."
            )
            last_error = e
            time.sleep(delay)

        except req.exceptions.Timeout as e:
            delay = RETRY_BASE_DELAY * attempt
            logger.warning(
                f"OpenRouter request timed out (attempt {attempt}/{MAX_RETRIES}). "
                f"Waiting {delay:.1f}s before retry..."
            )
            last_error = e
            time.sleep(delay)

    raise RuntimeError(
        f"OpenRouter API call failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _call_openai(
    prompt: str,
    llm_config: LLMConfig,
    api_key: str,
    base_url: Optional[str] = None,
) -> str:
    """
    Call the OpenAI API (or compatible endpoint) with retry logic.

    The openai library supports custom base_url, enabling use with:
    - OpenAI API (https://api.openai.com/v1)
    - Azure OpenAI
    - Local LLMs with OpenAI-compatible API (e.g., Ollama, LM Studio, vLLM)
    - Other proxy services

    Args:
        prompt: The prompt to send.
        llm_config: LLM configuration.
        api_key: The API key.
        base_url: Optional base URL override. Falls back to llm_config.base_url,
                  then to the OpenAI default (https://api.openai.com/v1).

    Returns:
        Response text from the model.
    """
    try:
        from openai import OpenAI, APIError, APIConnectionError, RateLimitError
    except ImportError:
        raise ImportError(
            "openai package is required. Install with: pip install openai"
        )

    resolved_base_url = base_url or llm_config.base_url or None
    client = OpenAI(
        api_key=api_key,
        base_url=resolved_base_url,
    )

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                f"Calling OpenAI API (model={llm_config.model}, "
                f"attempt={attempt}/{MAX_RETRIES})"
            )

            response = client.chat.completions.create(
                model=llm_config.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                max_tokens=MAX_RESPONSE_TOKENS,
                temperature=0.1,  # Low temperature for more deterministic/consistent output
            )

            # Guard against empty choices list — can occur with proxy APIs or
            # non-standard OpenAI-compatible endpoints that return 200 OK with no choices.
            if not response.choices:
                raise RuntimeError("LLM returned empty response (no choices in API response)")
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("LLM returned empty response")

            logger.info(
                f"OpenAI API call successful "
                f"(tokens: {response.usage.total_tokens if response.usage else 'unknown'})"
            )
            return content

        except RateLimitError as e:
            # Rate limit: wait longer before retrying
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (attempt {attempt}/{MAX_RETRIES}). "
                f"Waiting {delay:.1f}s before retry..."
            )
            last_error = e
            time.sleep(delay)

        except APIConnectionError as e:
            # Connection error: retry with backoff
            delay = RETRY_BASE_DELAY * attempt
            logger.warning(
                f"API connection error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                f"Waiting {delay:.1f}s before retry..."
            )
            last_error = e
            time.sleep(delay)

        except APIError as e:
            # Other API errors: retry if transient (5xx), fail immediately for 4xx
            if hasattr(e, 'status_code') and e.status_code and e.status_code < 500:
                # Client error (4xx): don't retry
                raise RuntimeError(f"OpenAI API client error: {e}") from e
            delay = RETRY_BASE_DELAY * attempt
            logger.warning(
                f"OpenAI API error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                f"Waiting {delay:.1f}s before retry..."
            )
            last_error = e
            time.sleep(delay)

    raise RuntimeError(
        f"OpenAI API call failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _call_anthropic(prompt: str, llm_config: LLMConfig, api_key: str) -> str:
    """
    Call the Anthropic API (Claude models) with retry logic.

    Args:
        prompt: The prompt to send.
        llm_config: LLM configuration.
        api_key: The Anthropic API key.

    Returns:
        Response text from the model.
    """
    try:
        import anthropic
        from anthropic import APIError, APIConnectionError, RateLimitError
    except ImportError:
        raise ImportError(
            "anthropic package is required. Install with: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                f"Calling Anthropic API (model={llm_config.model}, "
                f"attempt={attempt}/{MAX_RETRIES})"
            )

            message = client.messages.create(
                model=llm_config.model,
                max_tokens=MAX_RESPONSE_TOKENS,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            content = message.content[0].text if message.content else None
            if not content:
                raise RuntimeError("Anthropic API returned empty response")

            logger.info(
                f"Anthropic API call successful "
                f"(input_tokens={message.usage.input_tokens}, "
                f"output_tokens={message.usage.output_tokens})"
            )
            return content

        except RateLimitError as e:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Anthropic rate limit (attempt {attempt}/{MAX_RETRIES}). "
                f"Waiting {delay:.1f}s..."
            )
            last_error = e
            time.sleep(delay)

        except APIConnectionError as e:
            delay = RETRY_BASE_DELAY * attempt
            logger.warning(
                f"Anthropic connection error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                f"Waiting {delay:.1f}s..."
            )
            last_error = e
            time.sleep(delay)

        except APIError as e:
            if hasattr(e, 'status_code') and e.status_code and e.status_code < 500:
                raise RuntimeError(f"Anthropic API client error: {e}") from e
            delay = RETRY_BASE_DELAY * attempt
            logger.warning(
                f"Anthropic API error (attempt {attempt}/{MAX_RETRIES}): {e}. "
                f"Waiting {delay:.1f}s..."
            )
            last_error = e
            time.sleep(delay)

    raise RuntimeError(
        f"Anthropic API call failed after {MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )


def _call_plugin_provider(prompt: str, llm_config: LLMConfig, api_key: str) -> str:
    """
    Call a custom LLM provider loaded dynamically from a plugin module.

    The plugin module must implement:
        call_provider(prompt: str, config: LLMConfig, api_key: str) -> str

    Args:
        prompt: The prompt to send.
        llm_config: LLM configuration including plugin_module path.
        api_key: The API key retrieved from the environment.

    Returns:
        Response text from the provider.

    Raises:
        ImportError: If the plugin module cannot be imported.
        AttributeError: If the module does not implement call_provider().
        RuntimeError: If the provider call fails.
    """
    import importlib
    import re
    import sys
    from pathlib import Path

    module_path = llm_config.plugin_module

    # Security: only allow well-formed dotted module names (e.g. "pkg.sub.mod").
    # This prevents importlib.import_module() from being abused to load arbitrary
    # code via path traversal or injected characters from the requirements XML.
    if not module_path or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", module_path):
        raise ValueError(
            f"Invalid plugin_module '{module_path}'. Expected a dotted Python "
            "module path such as 'my_pkg.my_provider'."
        )

    logger.info(f"Loading LLM provider plugin: {module_path}")

    # Ensure the project root (cwd) is on sys.path so that plugin modules
    # in subdirectories (e.g. extensions/my_provider/) can be imported by dotted path.
    project_root = str(Path.cwd())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(
            f"Failed to import LLM provider plugin '{module_path}': {e}. "
            "Make sure the plugin module is installed and accessible."
        ) from e

    if not hasattr(module, "call_provider"):
        raise AttributeError(
            f"Plugin module '{module_path}' does not implement 'call_provider(prompt, config, api_key) -> str'."
        )

    logger.info(f"Calling plugin provider (model={llm_config.model})")
    try:
        result = module.call_provider(prompt, llm_config, api_key)
        if not isinstance(result, str):
            raise RuntimeError(
                f"Plugin provider returned {type(result).__name__}, expected str."
            )
        logger.info("Plugin provider call successful")
        return result
    except Exception as e:
        raise RuntimeError(f"Plugin provider '{module_path}' failed: {e}") from e
