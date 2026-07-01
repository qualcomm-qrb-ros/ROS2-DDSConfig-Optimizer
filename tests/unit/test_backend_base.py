# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the DDSBackend abstract base class."""

import pytest

from dds_optimizer.backends.base import DDSBackend


def test_cannot_instantiate_abstract_base():
    """DDSBackend is abstract and must not be directly instantiable."""
    with pytest.raises(TypeError):
        DDSBackend()


def test_concrete_subclass_must_implement_all_abstract_methods():
    """A subclass missing an abstract method cannot be instantiated."""

    class Incomplete(DDSBackend):
        name = "incomplete"
        profiles_env_var = "X"
        rmw_implementation = "y"
        # missing knowledge_base_path/prompt_expertise/generate_config/validate_config

    with pytest.raises(TypeError):
        Incomplete()
