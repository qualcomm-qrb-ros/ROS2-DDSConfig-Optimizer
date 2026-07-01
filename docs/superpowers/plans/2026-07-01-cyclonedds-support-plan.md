# CycloneDDS Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CycloneDDS as a second, per-run-selectable DDS backend alongside the existing FastDDS optimizer, in one codebase, via a thin `DDSBackend` abstraction.

**Architecture:** Rename `fastdds_optimizer` → `dds_optimizer`. Introduce a `backends/` package with an abstract `DDSBackend`, a name→backend registry, a FastDDS backend that wraps the existing generator/validator/deployer, and a CycloneDDS backend with a generic `xml_path`-driven XML generator. The shared core (loop, LLM, benchmark, prompt) routes all vendor-specific steps (KB path, prompt wording, config generate/validate, deploy env var, RMW implementation) through the backend object. Vendor is chosen by a `<dds_implementation>` field in `user_requirements.xml` (default `fastdds`).

**Tech Stack:** Python 3.12, pydantic v2, `xml.etree.ElementTree`, pytest, `uv`. All work happens on the `iq10` device (ADB) at `/root/nasong/ROS2-DDSConfig-Optimizer`, branch `cyclone-dds`. LLM calls use OpenRouter (`LLM_API_KEY`).

---

## Environment Notes (read first)

- **All file operations target the iq10 device** via the remote-device MCP tools (`adb_read`, `adb_write`, `adb_exec`). There is no local checkout.
- **Run commands with** `adb_exec` and `cd /root/nasong/ROS2-DDSConfig-Optimizer && <cmd>`. Disable git pagers: append `| cat` or use `git --no-pager`.
- **Tests run via** `uv run pytest ...`.
- **Git**: branch is `cyclone-dds`. Commit after each task. End commit messages with the Co-Authored-By trailer.
- **Import style in tests**: absolute, e.g. `from dds_optimizer.models import DDSParameterSet` (after rename).

---

## File Structure (target)

```
src/dds_optimizer/                       (git mv from src/fastdds_optimizer)
├── backends/                            ← NEW package
│   ├── __init__.py
│   ├── base.py                          DDSBackend ABC
│   ├── registry.py                      get_backend(name) -> DDSBackend
│   ├── fastdds/
│   │   ├── __init__.py
│   │   └── backend.py                   wraps config/generator.py + validator.py + deployer.py
│   └── cyclonedds/
│       ├── __init__.py
│       ├── backend.py
│       ├── generator.py                 ← NEW generic xml_path-driven generator
│       └── validator.py                 ← NEW structural validator
├── config/                              existing FastDDS generator/validator/deployer (retained)
├── llm/prompt_builder.py                parameterized by backend
├── optimizer/optimization_loop.py       resolves backend once, routes through it
├── benchmark/launcher.py                exports profiles env var + RMW_IMPLEMENTATION
├── requirements/parser.py               parses <dds_implementation>
├── models.py                            RequirementsConfig gains dds_implementation
├── main.py                              prog name dds-optimizer; per-backend export line
└── ... (environment/, dashboard/, utils/, unchanged in logic)

data/knowledge_base/
├── fastdds/
│   ├── performance_critical_params.json   (moved from data/knowledge_base/)
│   └── fast_dds_complete_params.json      (moved)
└── cyclonedds/
    └── performance_critical_params.json   (moved from cyclonedds-config-summary/)

example/
└── cyclonedds_config.xml                (copied reference initial config)
```

---

## Task 1: Package rename `fastdds_optimizer` → `dds_optimizer`

**Files:**
- Rename: `src/fastdds_optimizer/` → `src/dds_optimizer/` (git mv)
- Modify: all `.py` importing `fastdds_optimizer` (9 in `src`, plus tests updated in later step of THIS task)
- Modify: `pyproject.toml` (scripts, wheel packages, keywords)
- Modify: `scripts/test_all_components.sh` (import + command names)
- Test: full existing suite must still pass

- [ ] **Step 1: Move the package directory (preserve history)**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git mv src/fastdds_optimizer src/dds_optimizer && git status -s | cat
```
Expected: renames listed under `src/dds_optimizer/...`.

- [ ] **Step 2: Rewrite absolute import references in source**

These `src` files use the absolute name `fastdds_optimizer` (not relative imports):
`utils/logger.py`, `environment/collector.py`, `environment/ros2_api.py`, `llm/llm_client.py`.
Replace every `fastdds_optimizer` token with `dds_optimizer` in all source files:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && grep -rl "fastdds_optimizer" src | xargs sed -i 's/fastdds_optimizer/dds_optimizer/g' && grep -rn "fastdds_optimizer" src | cat
```
Expected: final grep prints nothing (no remaining references in `src`).

- [ ] **Step 3: Rewrite import references in tests and scripts**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && grep -rl "fastdds_optimizer" tests scripts | xargs sed -i 's/fastdds_optimizer/dds_optimizer/g' && grep -rn "fastdds_optimizer" tests scripts | cat
```
Expected: final grep prints nothing.

- [ ] **Step 4: Update `pyproject.toml`**

Change these three locations exactly:
```toml
keywords = ["fastdds", "cyclonedds", "ros2", "optimization", "dds", "performance"]
```
```toml
[project.scripts]
dds-optimizer = "dds_optimizer.main:main"
```
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/dds_optimizer"]
```
(No backward-compat `fastdds-optimizer` alias — confirmed with user.)

- [ ] **Step 5: Update `main.py` CLI naming**

In `src/dds_optimizer/main.py`, change `prog="fastdds-optimizer"` → `prog="dds-optimizer"`, and update the four example command lines in the `epilog` string and the `run`/`dashboard` help text from `fastdds-optimizer` to `dds-optimizer`.
(The per-backend export line in `cmd_run` is handled in Task 9 — leave the FastDDS export text for now.)

- [ ] **Step 6: Reinstall the package so the new import name resolves**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv sync 2>&1 | tail -5
```
Expected: sync completes; a `dds_optimizer` (editable) install is present.

- [ ] **Step 7: Run the full existing suite to confirm the rename broke nothing**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/ -q 2>&1 | tail -20
```
Expected: all tests PASS (same count as before the rename). If any fail with `ModuleNotFoundError: fastdds_optimizer`, a reference was missed — re-run the greps in Steps 2–3.

- [ ] **Step 8: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "refactor: rename fastdds_optimizer package to dds_optimizer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Relocate knowledge bases into per-vendor folders

**Files:**
- Move: `data/knowledge_base/performance_critical_params.json` → `data/knowledge_base/fastdds/performance_critical_params.json`
- Move: `data/knowledge_base/fast_dds_complete_params.json` → `data/knowledge_base/fastdds/fast_dds_complete_params.json`
- Move: `cyclonedds-config-summary/cyclonedds_performance_critical_params.json` → `data/knowledge_base/cyclonedds/performance_critical_params.json`

> The `prompt_builder.py` hardcoded path breaks after this move; it is fixed in Task 7. Do Task 2 → 7 close together, or expect `test_prompt_builder_topology.py` to fail on KB-not-found until Task 7. To keep the suite green between commits, this task only MOVES files; Task 7 updates the loader.

- [ ] **Step 1: Create vendor folders and move the FastDDS KBs**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && mkdir -p data/knowledge_base/fastdds data/knowledge_base/cyclonedds && git mv data/knowledge_base/performance_critical_params.json data/knowledge_base/fastdds/performance_critical_params.json && git mv data/knowledge_base/fast_dds_complete_params.json data/knowledge_base/fastdds/fast_dds_complete_params.json && ls data/knowledge_base/fastdds
```
Expected: both JSON files listed under `data/knowledge_base/fastdds`.

- [ ] **Step 2: Copy the CycloneDDS KB into place**

`cyclonedds-config-summary/` is an untracked nested git checkout, so copy (not git mv) its KB into the tracked tree:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && cp cyclonedds-config-summary/cyclonedds_performance_critical_params.json data/knowledge_base/cyclonedds/performance_critical_params.json && python3 -c "import json; d=json.load(open('data/knowledge_base/cyclonedds/performance_critical_params.json')); print('params:', len(d['parameters']))"
```
Expected: `params: 40`.

- [ ] **Step 3: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "chore: reorganize knowledge bases into per-vendor folders

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `DDSBackend` abstract base class

**Files:**
- Create: `src/dds_optimizer/backends/__init__.py`
- Create: `src/dds_optimizer/backends/base.py`
- Test: `tests/unit/test_backend_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_backend_base.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_backend_base.py -v 2>&1 | tail -15
```
Expected: FAIL with `ModuleNotFoundError: No module named 'dds_optimizer.backends'`.

- [ ] **Step 3: Create the package init**

Write `src/dds_optimizer/backends/__init__.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""DDS vendor backends (FastDDS, CycloneDDS) and the selection registry."""
```

- [ ] **Step 4: Write the abstract base class**

Write `src/dds_optimizer/backends/base.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
DDSBackend: the abstraction that isolates all vendor-specific behavior.

The shared optimizer core (loop, LLM, benchmark, prompt builder) interacts
only with a DDSBackend instance for the steps that differ between DDS
implementations:
  - which knowledge base file to load,
  - the system-prompt opening line + any format notes,
  - how to generate a config file from a params dict,
  - how to validate that config file,
  - the environment variable a benchmark subprocess must set to load the
    config, and the RMW implementation ROS2 must use.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List


class DDSBackend(ABC):
    """Abstract base for a DDS vendor backend."""

    #: Vendor identifier, e.g. "fastdds" | "cyclonedds".
    name: str
    #: Env var pointing at the profiles/config file the DDS impl reads.
    profiles_env_var: str
    #: RMW implementation ROS2 must use for this vendor.
    rmw_implementation: str

    @abstractmethod
    def knowledge_base_path(self) -> Path:
        """Absolute path to this backend's performance_critical_params.json."""

    @abstractmethod
    def prompt_expertise(self) -> str:
        """System-prompt opening line + any vendor-specific format notes."""

    @abstractmethod
    def generate_config(self, params: Dict, out_path: Path) -> Path:
        """Generate a vendor config file from a param name→value dict."""

    @abstractmethod
    def validate_config(self, config_path: Path) -> List[str]:
        """Validate a generated config; return a list of warning strings."""
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_backend_base.py -v 2>&1 | tail -15
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: add DDSBackend abstract base class

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: CycloneDDS generic `xml_path`-driven generator

**Files:**
- Create: `src/dds_optimizer/backends/cyclonedds/__init__.py`
- Create: `src/dds_optimizer/backends/cyclonedds/generator.py`
- Test: `tests/unit/test_cyclonedds_generator.py`

The KB gives each parameter an `xml_path` (e.g. `CycloneDDS/Domain/Internal/AckDelay`, or `.../SocketReceiveBufferSize/@min` for attributes). The generator emits only the params present in `params` (sparse), sharing parent nodes, and passes values through verbatim.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cyclonedds_generator.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the generic xml_path-driven CycloneDDS config generator."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dds_optimizer.backends.cyclonedds.generator import generate_cyclonedds_config

# Minimal KB stub covering element paths, a shared parent, and @attr paths.
KB = {
    "parameters": {
        "ack_delay": {"xml_path": "CycloneDDS/Domain/Internal/AckDelay"},
        "nack_delay": {"xml_path": "CycloneDDS/Domain/Internal/NackDelay"},
        "max_message_size": {"xml_path": "CycloneDDS/Domain/General/MaxMessageSize"},
        "socket_receive_buffer_size": {
            "xml_path": "CycloneDDS/Domain/Internal/SocketReceiveBufferSize/@min"
        },
    }
}

NS = "{https://cdds.io/config}"


def _generate(params: dict, tmp_path: Path) -> ET.Element:
    out = tmp_path / "cyclonedds.xml"
    generate_cyclonedds_config(params, KB, out)
    return ET.parse(out).getroot()


def test_root_and_domain(tmp_path):
    root = _generate({"ack_delay": "10 ms"}, tmp_path)
    assert root.tag == f"{NS}CycloneDDS"
    domain = root.find(f"{NS}Domain")
    assert domain is not None
    assert domain.get("Id") == "any"


def test_element_text_is_set_verbatim(tmp_path):
    root = _generate({"max_message_size": "65500B"}, tmp_path)
    el = root.find(f"{NS}Domain/{NS}General/{NS}MaxMessageSize")
    assert el is not None
    assert el.text == "65500B"


def test_attribute_path_sets_attribute_not_text(tmp_path):
    root = _generate({"socket_receive_buffer_size": "8 MiB"}, tmp_path)
    el = root.find(f"{NS}Domain/{NS}Internal/{NS}SocketReceiveBufferSize")
    assert el is not None
    assert el.get("min") == "8 MiB"
    assert (el.text or "").strip() == ""


def test_parent_nodes_are_shared(tmp_path):
    root = _generate({"ack_delay": "5 ms", "nack_delay": "50 ms"}, tmp_path)
    internals = root.findall(f"{NS}Domain/{NS}Internal")
    assert len(internals) == 1  # AckDelay and NackDelay share one <Internal>
    assert internals[0].find(f"{NS}AckDelay").text == "5 ms"
    assert internals[0].find(f"{NS}NackDelay").text == "50 ms"


def test_sparse_output_only_set_params_appear(tmp_path):
    root = _generate({"ack_delay": "10 ms"}, tmp_path)
    # No General branch when no General param was set.
    assert root.find(f"{NS}Domain/{NS}General") is None
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}NackDelay") is None


def test_unknown_param_is_ignored(tmp_path):
    # A param not in the KB is skipped rather than raising.
    root = _generate({"ack_delay": "10 ms", "not_a_real_param": 1}, tmp_path)
    assert root.find(f"{NS}Domain/{NS}Internal/{NS}AckDelay").text == "10 ms"


def test_output_is_wellformed_xml_with_declaration(tmp_path):
    out = tmp_path / "c.xml"
    generate_cyclonedds_config({"ack_delay": "10 ms"}, KB, out)
    content = out.read_text()
    assert content.startswith("<?xml")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_cyclonedds_generator.py -v 2>&1 | tail -20
```
Expected: FAIL — `ModuleNotFoundError: No module named 'dds_optimizer.backends.cyclonedds'`.

- [ ] **Step 3: Create the package init**

Write `src/dds_optimizer/backends/cyclonedds/__init__.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""CycloneDDS backend: generic generator, validator, and DDSBackend impl."""
```

- [ ] **Step 4: Write the generator**

Write `src/dds_optimizer/backends/cyclonedds/generator.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Generic xml_path-driven CycloneDDS config generator.

Each performance-critical parameter in the CycloneDDS knowledge base carries an
`xml_path`, e.g.:
  "ack_delay":                  "CycloneDDS/Domain/Internal/AckDelay"          (element text)
  "socket_receive_buffer_size": ".../SocketReceiveBufferSize/@min"             (attribute)

Mechanism:
  1. Sparse — emit only params the LLM actually set; CycloneDDS treats absent
     elements as "use default", so we never fill defaults.
  2. Path-driven — split xml_path on '/', get-or-create each parent node,
     caching by path prefix so siblings share a parent (e.g. AckDelay and
     NackDelay share one <Internal>).
  3. '@attr' — if the last segment starts with '@', set that attribute on the
     second-to-last node; otherwise set the element's .text.
  4. <Domain Id="any"> — set Id="any" on the Domain node (matches the
     reference cyclonedds_config.xml).
  5. Values pass through verbatim — CycloneDDS accepts unit-suffixed strings
     ("64 KiB", "100 ms"); no conversion.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

from ...utils.logger import get_logger

logger = get_logger(__name__)

CYCLONEDDS_NAMESPACE = "https://cdds.io/config"


def _str(value) -> str:
    """XML string form; bools lowercased to match CycloneDDS conventions."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _apply_path(root: ET.Element, cache: Dict[str, ET.Element], segments, value) -> None:
    """
    Walk/create the node path (segments[0] is the already-created root's tag)
    and set the element text or attribute for the final segment.
    """
    last = segments[-1]
    is_attr = last.startswith("@")

    # Path segments that identify ELEMENTS (drop a trailing @attr).
    element_segments = segments[:-1] if is_attr else segments

    node = root
    prefix = element_segments[0]  # matches root tag ("CycloneDDS")
    for seg in element_segments[1:]:
        prefix = f"{prefix}/{seg}"
        child = cache.get(prefix)
        if child is None:
            child = ET.SubElement(node, seg)
            if seg == "Domain":
                child.set("Id", "any")
            cache[prefix] = child
        node = child

    if is_attr:
        node.set(last[1:], _str(value))
    else:
        node.text = _str(value)


def generate_cyclonedds_config(params: Dict, kb: Dict, out_path: Path) -> Path:
    """
    Generate a CycloneDDS XML config from a param name→value dict.

    Args:
        params: LLM-set parameter names → values (sparse; only these are emitted).
        kb: The CycloneDDS knowledge base dict (must have kb["parameters"][name]["xml_path"]).
        out_path: Where to write the XML file.

    Returns:
        out_path.
    """
    kb_params = kb.get("parameters", {})

    root = ET.Element("CycloneDDS")
    root.set("xmlns", CYCLONEDDS_NAMESPACE)
    cache: Dict[str, ET.Element] = {"CycloneDDS": root}

    for name, value in params.items():
        info = kb_params.get(name)
        if not info or "xml_path" not in info:
            logger.warning(f"CycloneDDS param '{name}' not in knowledge base; skipping.")
            continue
        segments = info["xml_path"].split("/")
        _apply_path(root, cache, segments, value)

    _indent_xml(root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8" ?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    logger.info(f"Generated CycloneDDS config: {out_path}")
    return out_path


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print indentation in-place (same approach as the FastDDS generator)."""
    indent = "\n" + "    " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "    "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
    if not level:
        elem.tail = "\n"
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_cyclonedds_generator.py -v 2>&1 | tail -20
```
Expected: 7 passed.

- [ ] **Step 6: Sanity-check against the REAL KB (all 40 params)**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run python -c "
import json
from pathlib import Path
from dds_optimizer.backends.cyclonedds.generator import generate_cyclonedds_config
kb = json.load(open('data/knowledge_base/cyclonedds/performance_critical_params.json'))
params = {n: v.get('default') for n, v in kb['parameters'].items()}
out = Path('/tmp/cyc_all.xml')
generate_cyclonedds_config(params, kb, out)
import xml.etree.ElementTree as ET
ET.parse(out)  # raises if malformed
print('OK: generated + parsed', len(params), 'params')
print(out.read_text()[:400])
"
```
Expected: `OK: generated + parsed 40 params` and a well-formed XML snippet.

- [ ] **Step 7: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: add generic xml_path-driven CycloneDDS config generator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: CycloneDDS structural validator

**Files:**
- Create: `src/dds_optimizer/backends/cyclonedds/validator.py`
- Test: `tests/unit/test_cyclonedds_validator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cyclonedds_validator.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the CycloneDDS structural validator."""

from pathlib import Path

import pytest

from dds_optimizer.backends.cyclonedds.validator import (
    validate_cyclonedds_config,
    CycloneConfigValidationError,
)

WELLFORMED = (
    '<?xml version="1.0" encoding="UTF-8" ?>\n'
    '<CycloneDDS xmlns="https://cdds.io/config">'
    '<Domain Id="any"><Internal><AckDelay>10 ms</AckDelay></Internal></Domain>'
    '</CycloneDDS>'
)


def test_valid_config_has_no_warnings(tmp_path):
    p = tmp_path / "ok.xml"
    p.write_text(WELLFORMED)
    assert validate_cyclonedds_config(p) == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(CycloneConfigValidationError):
        validate_cyclonedds_config(tmp_path / "nope.xml")


def test_malformed_xml_raises(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<CycloneDDS><Domain></CycloneDDS>")  # mismatched tags
    with pytest.raises(CycloneConfigValidationError):
        validate_cyclonedds_config(p)


def test_wrong_root_warns(tmp_path):
    p = tmp_path / "root.xml"
    p.write_text('<NotCyclone xmlns="https://cdds.io/config"><Domain/></NotCyclone>')
    warnings = validate_cyclonedds_config(p)
    assert any("root" in w.lower() for w in warnings)


def test_missing_domain_warns(tmp_path):
    p = tmp_path / "nodomain.xml"
    p.write_text('<CycloneDDS xmlns="https://cdds.io/config"></CycloneDDS>')
    warnings = validate_cyclonedds_config(p)
    assert any("domain" in w.lower() for w in warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_cyclonedds_validator.py -v 2>&1 | tail -20
```
Expected: FAIL — `ModuleNotFoundError` for `...cyclonedds.validator`.

- [ ] **Step 3: Write the validator**

Write `src/dds_optimizer/backends/cyclonedds/validator.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
CycloneDDS config validator (lightweight).

Sparse generation already guarantees structural correctness, so validation only
confirms: file exists, well-formed XML, root local-name is CycloneDDS, and at
least one Domain element is present. Structural problems are non-fatal warnings;
a missing file or malformed XML is a hard error.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from ...utils.logger import get_logger

logger = get_logger(__name__)


class CycloneConfigValidationError(Exception):
    """Raised when the CycloneDDS config cannot be read or parsed."""


def _local(tag: str) -> str:
    """Strip an XML namespace prefix: '{ns}Tag' -> 'Tag'."""
    return tag.rsplit("}", 1)[-1]


def validate_cyclonedds_config(config_path: Path) -> List[str]:
    """Validate a CycloneDDS XML config; return a list of warning strings."""
    if not Path(config_path).exists():
        raise CycloneConfigValidationError(f"Config file not found: {config_path}")
    if not Path(config_path).is_file():
        raise CycloneConfigValidationError(f"Config path is not a file: {config_path}")

    try:
        tree = ET.parse(config_path)
    except ET.ParseError as e:
        raise CycloneConfigValidationError(
            f"Malformed CycloneDDS XML '{config_path}': {e}"
        ) from e

    warnings: List[str] = []
    root = tree.getroot()

    if _local(root.tag) != "CycloneDDS":
        warnings.append(
            f"Unexpected root element <{_local(root.tag)}>; expected <CycloneDDS>."
        )

    domains = [c for c in root.iter() if _local(c.tag) == "Domain"]
    if not domains:
        warnings.append("No <Domain> element found in CycloneDDS config.")

    for w in warnings:
        logger.warning(f"CycloneDDS config warning: {w}")
    return warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_cyclonedds_validator.py -v 2>&1 | tail -20
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: add CycloneDDS structural validator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Concrete backends (FastDDS + CycloneDDS) and the registry

**Files:**
- Create: `src/dds_optimizer/backends/fastdds/__init__.py`
- Create: `src/dds_optimizer/backends/fastdds/backend.py`
- Create: `src/dds_optimizer/backends/cyclonedds/backend.py`
- Create: `src/dds_optimizer/backends/registry.py`
- Test: `tests/unit/test_backend_registry.py`

Note the FastDDS generator takes a `DDSParameterSet`, while `DDSBackend.generate_config` takes a plain dict — the FastDDS backend wraps the dict in `DDSParameterSet`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_backend_registry.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the backend registry and the two concrete backends."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from dds_optimizer.backends.registry import get_backend
from dds_optimizer.backends.base import DDSBackend


def test_get_fastdds_backend():
    b = get_backend("fastdds")
    assert isinstance(b, DDSBackend)
    assert b.name == "fastdds"
    assert b.profiles_env_var == "FASTRTPS_DEFAULT_PROFILES_FILE"
    assert b.rmw_implementation == "rmw_fastrtps_cpp"


def test_get_cyclonedds_backend():
    b = get_backend("cyclonedds")
    assert isinstance(b, DDSBackend)
    assert b.name == "cyclonedds"
    assert b.profiles_env_var == "CYCLONEDDS_URI"
    assert b.rmw_implementation == "rmw_cyclonedds_cpp"


def test_get_backend_is_case_insensitive():
    assert get_backend("FastDDS").name == "fastdds"


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        get_backend("nosuchdds")


def test_knowledge_base_paths_exist():
    for name in ("fastdds", "cyclonedds"):
        kb = get_backend(name).knowledge_base_path()
        assert kb.exists(), f"{name} KB not found at {kb}"


def test_prompt_expertise_mentions_vendor():
    assert "fast" in get_backend("fastdds").prompt_expertise().lower()
    assert "cyclone" in get_backend("cyclonedds").prompt_expertise().lower()


def test_cyclonedds_backend_generates_and_validates(tmp_path):
    b = get_backend("cyclonedds")
    out = tmp_path / "c.xml"
    b.generate_config({"ack_delay": "10 ms"}, out)
    assert out.exists()
    assert b.validate_config(out) == []
    root = ET.parse(out).getroot()
    assert root.tag.endswith("CycloneDDS")


def test_fastdds_backend_generates_and_validates(tmp_path):
    b = get_backend("fastdds")
    out = tmp_path / "f.xml"
    b.generate_config({"history_depth": 10, "reliability_kind": "RELIABLE"}, out)
    assert out.exists()
    # FastDDS validator returns a (possibly empty) list of warnings.
    assert isinstance(b.validate_config(out), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_backend_registry.py -v 2>&1 | tail -20
```
Expected: FAIL — `ModuleNotFoundError: No module named 'dds_optimizer.backends.registry'`.

- [ ] **Step 3: Write the FastDDS backend**

Write `src/dds_optimizer/backends/fastdds/__init__.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""FastDDS backend: wraps the existing config generator/validator/deployer."""
```

Write `src/dds_optimizer/backends/fastdds/backend.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""FastDDS backend — wraps the hand-written FastDDS generator and validator."""

from pathlib import Path
from typing import Dict, List

from ...config.generator import generate_fastdds_config
from ...config.validator import validate_config as validate_fastdds_config
from ...models import DDSParameterSet
from ..base import DDSBackend

# FastDDS KB lives under data/knowledge_base/fastdds/. This file is at
# src/dds_optimizer/backends/fastdds/backend.py → parents[4] is the repo root.
_KB_PATH = (
    Path(__file__).resolve().parents[4]
    / "data" / "knowledge_base" / "fastdds" / "performance_critical_params.json"
)


class FastDDSBackend(DDSBackend):
    name = "fastdds"
    profiles_env_var = "FASTRTPS_DEFAULT_PROFILES_FILE"
    rmw_implementation = "rmw_fastrtps_cpp"

    def knowledge_base_path(self) -> Path:
        return _KB_PATH

    def prompt_expertise(self) -> str:
        return (
            "You are an expert in FastDDS (eProsima Fast DDS) configuration "
            "optimization for ROS2."
        )

    def generate_config(self, params: Dict, out_path: Path) -> Path:
        return generate_fastdds_config(DDSParameterSet(parameters=dict(params)), out_path)

    def validate_config(self, config_path: Path) -> List[str]:
        return validate_fastdds_config(config_path)
```

- [ ] **Step 4: Write the CycloneDDS backend**

Write `src/dds_optimizer/backends/cyclonedds/backend.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""CycloneDDS backend — generic generator + lightweight validator."""

import json
from pathlib import Path
from typing import Dict, List

from ...utils.logger import get_logger
from ..base import DDSBackend
from .generator import generate_cyclonedds_config
from .validator import validate_cyclonedds_config

logger = get_logger(__name__)

_KB_PATH = (
    Path(__file__).resolve().parents[4]
    / "data" / "knowledge_base" / "cyclonedds" / "performance_critical_params.json"
)


class CycloneDDSBackend(DDSBackend):
    name = "cyclonedds"
    profiles_env_var = "CYCLONEDDS_URI"
    rmw_implementation = "rmw_cyclonedds_cpp"

    def __init__(self) -> None:
        self._kb_cache: Dict = {}

    def knowledge_base_path(self) -> Path:
        return _KB_PATH

    def _kb(self) -> Dict:
        if not self._kb_cache:
            with open(self.knowledge_base_path()) as f:
                self._kb_cache = json.load(f)
        return self._kb_cache

    def prompt_expertise(self) -> str:
        return (
            "You are an expert in Eclipse CycloneDDS configuration optimization "
            "for ROS2.\n"
            "NOTE: CycloneDDS parameter values are unit-suffixed strings, e.g. "
            '"8 MiB", "100 ms", "65500B". Emit values in that form.'
        )

    def generate_config(self, params: Dict, out_path: Path) -> Path:
        return generate_cyclonedds_config(dict(params), self._kb(), out_path)

    def validate_config(self, config_path: Path) -> List[str]:
        return validate_cyclonedds_config(config_path)
```

- [ ] **Step 5: Write the registry**

Write `src/dds_optimizer/backends/registry.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Registry mapping a vendor name to a DDSBackend instance."""

from .base import DDSBackend
from .cyclonedds.backend import CycloneDDSBackend
from .fastdds.backend import FastDDSBackend

SUPPORTED_BACKENDS = ("fastdds", "cyclonedds")


def get_backend(name: str) -> DDSBackend:
    """
    Return a DDSBackend instance for the given vendor name (case-insensitive).

    Raises:
        ValueError: if name is not a supported backend.
    """
    key = (name or "").strip().lower()
    if key == "fastdds":
        return FastDDSBackend()
    if key == "cyclonedds":
        return CycloneDDSBackend()
    raise ValueError(
        f"Unsupported DDS implementation '{name}'. "
        f"Must be one of: {SUPPORTED_BACKENDS}."
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_backend_registry.py -v 2>&1 | tail -25
```
Expected: 8 passed. (This confirms `parents[4]` resolves the KB paths correctly.)

- [ ] **Step 7: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: add FastDDS/CycloneDDS backends and selection registry

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Parameterize the prompt builder by backend

**Files:**
- Modify: `src/dds_optimizer/llm/prompt_builder.py`
- Test: `tests/unit/test_prompt_builder_backend.py` (new); existing `test_prompt_builder_topology.py` must still pass

The prompt builder currently hardcodes the KB path and "expert in FastDDS" wording. Add a `backend` parameter threaded from the loop. Keep backward-compatible behavior: when `backend` is None, default to FastDDS KB + wording so existing tests pass.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_prompt_builder_backend.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""The feedback prompt must reflect the selected backend (KB + wording)."""

from dds_optimizer.backends.registry import get_backend
from dds_optimizer.llm.prompt_builder import build_feedback_prompt
from dds_optimizer.models import (
    BenchmarkConfig,
    EnvironmentInfo,
    LatencyRequirement,
    PerformanceRequirements,
    RequirementsConfig,
)


def _reqs() -> RequirementsConfig:
    return RequirementsConfig(
        benchmark=BenchmarkConfig(test_file="/tmp/b.py"),
        performance_requirements=PerformanceRequirements(
            latency=LatencyRequirement(optional=False, target_mean_ms=10.0)
        ),
    )


def _env() -> EnvironmentInfo:
    return EnvironmentInfo(os_version="Ubuntu 24.04", ros2_distro="jazzy")


def test_cyclonedds_prompt_uses_cyclone_wording_and_params():
    prompt = build_feedback_prompt(
        requirements=_reqs(),
        env=_env(),
        current_config_params={},
        results=None,
        performance_gaps={},
        iteration=2,
        backend=get_backend("cyclonedds"),
    )
    assert "CycloneDDS" in prompt
    assert "ack_delay" in prompt              # a CycloneDDS KB param
    assert "Available cyclonedds Parameters" in prompt


def test_fastdds_prompt_uses_fastdds_params():
    prompt = build_feedback_prompt(
        requirements=_reqs(),
        env=_env(),
        current_config_params={},
        results=None,
        performance_gaps={},
        iteration=2,
        backend=get_backend("fastdds"),
    )
    assert "FastDDS" in prompt
    assert "Available fastdds Parameters" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_prompt_builder_backend.py -v 2>&1 | tail -20
```
Expected: FAIL — `build_feedback_prompt() got an unexpected keyword argument 'backend'`.

- [ ] **Step 3: Update `_load_performance_critical_params` to accept a path**

In `src/dds_optimizer/llm/prompt_builder.py`, replace the module-level `_KNOWLEDGE_BASE_PATH` constant and `_load_performance_critical_params()` with a path-parameterized loader. Delete the old `_KNOWLEDGE_BASE_PATH` block:
```python
# Fallback KB path when no backend is supplied (backward compatibility).
_DEFAULT_KB_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "data" / "knowledge_base" / "fastdds" / "performance_critical_params.json"
)


def _load_performance_critical_params(kb_path: Optional[Path] = None) -> Dict:
    """Load the performance-critical parameters knowledge base."""
    path = kb_path or _DEFAULT_KB_PATH
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}
```

- [ ] **Step 4: Parameterize the params-reference table title**

In `_format_params_reference`, change the hardcoded title. Replace the signature and the title line:
```python
def _format_params_reference(params_data: Dict, backend_name: str = "FastDDS") -> str:
```
and change:
```python
        "## Available FastDDS Parameters",
```
to:
```python
        f"## Available {backend_name} Parameters",
```

- [ ] **Step 5: Thread `backend` through `build_feedback_prompt`**

In `build_feedback_prompt`, add a `backend` keyword parameter (import `DDSBackend` for typing at the top: `from ..backends.base import DDSBackend`). Add to the signature (after `pipeline_topology`):
```python
    backend: Optional[DDSBackend] = None,
```
Immediately after the `situation = (...)` blocks and before `params_data = _load_performance_critical_params()`, insert:
```python
    # Backend-specific KB path, table title, and system-prompt opening line.
    if backend is not None:
        kb_path = backend.knowledge_base_path()
        backend_label = backend.name
        expertise_line = backend.prompt_expertise()
    else:
        kb_path = None
        backend_label = "FastDDS"
        expertise_line = (
            "You are an expert in FastDDS (eProsima Fast DDS) configuration "
            "optimization for ROS2."
        )
```
Change the params load + reference lines to:
```python
    params_data = _load_performance_critical_params(kb_path)
    params_reference = _format_params_reference(params_data, backend_label)
```
In the `system_context` f-string, replace the first line:
```python
    system_context = f"""You are an expert in FastDDS (eProsima Fast DDS) configuration optimization for ROS2.
```
with:
```python
    system_context = f"""{expertise_line}
```

- [ ] **Step 6: Run both prompt tests to verify they pass**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_prompt_builder_backend.py tests/unit/test_prompt_builder_topology.py -v 2>&1 | tail -25
```
Expected: all pass (new backend tests + existing topology tests). The topology tests pass because `backend` defaults to None → FastDDS KB at the new path.

- [ ] **Step 7: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: parameterize prompt builder by DDS backend

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Vendor selection — models + requirements parser

**Files:**
- Modify: `src/dds_optimizer/models.py` (`RequirementsConfig`)
- Modify: `src/dds_optimizer/requirements/parser.py`
- Test: additions to `tests/unit/test_requirements_parser.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_requirements_parser.py` (reuse its existing imports/helpers; if it writes XML to a temp file, mirror that style). Add:
```python
def test_dds_implementation_defaults_to_fastdds(tmp_path):
    xml = tmp_path / "req.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<optimization_requirements>'
        '<benchmark><test_file>/tmp/b.py</test_file></benchmark>'
        '<performance_requirements>'
        '<latency optional="false"><target_mean_ms>10</target_mean_ms></latency>'
        '</performance_requirements>'
        '<llm_config><provider>openrouter</provider><model>m</model>'
        '<api_key_env>LLM_API_KEY</api_key_env></llm_config>'
        '</optimization_requirements>'
    )
    from dds_optimizer.requirements.parser import parse_requirements
    cfg = parse_requirements(str(xml))
    assert cfg.dds_implementation == "fastdds"


def test_dds_implementation_parsed_cyclonedds(tmp_path):
    xml = tmp_path / "req.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<optimization_requirements>'
        '<dds_implementation>cyclonedds</dds_implementation>'
        '<benchmark><test_file>/tmp/b.py</test_file></benchmark>'
        '<performance_requirements>'
        '<latency optional="false"><target_mean_ms>10</target_mean_ms></latency>'
        '</performance_requirements>'
        '<llm_config><provider>openrouter</provider><model>m</model>'
        '<api_key_env>LLM_API_KEY</api_key_env></llm_config>'
        '</optimization_requirements>'
    )
    from dds_optimizer.requirements.parser import parse_requirements
    cfg = parse_requirements(str(xml))
    assert cfg.dds_implementation == "cyclonedds"


def test_invalid_dds_implementation_raises(tmp_path):
    xml = tmp_path / "req.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<optimization_requirements>'
        '<dds_implementation>nosuchdds</dds_implementation>'
        '<benchmark><test_file>/tmp/b.py</test_file></benchmark>'
        '<performance_requirements>'
        '<latency optional="false"><target_mean_ms>10</target_mean_ms></latency>'
        '</performance_requirements>'
        '<llm_config><provider>openrouter</provider><model>m</model>'
        '<api_key_env>LLM_API_KEY</api_key_env></llm_config>'
        '</optimization_requirements>'
    )
    from dds_optimizer.requirements.parser import parse_requirements
    import pytest
    with pytest.raises(ValueError):
        parse_requirements(str(xml))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_requirements_parser.py -k dds_implementation -v 2>&1 | tail -20
```
Expected: FAIL — `RequirementsConfig` has no attribute `dds_implementation`.

- [ ] **Step 3: Add the field to `RequirementsConfig`**

In `src/dds_optimizer/models.py`, in `class RequirementsConfig`, add the field (after `llm_config`):
```python
    dds_implementation: str = "fastdds"
```
And add a validator inside the class:
```python
    @field_validator("dds_implementation")
    @classmethod
    def validate_dds_implementation(cls, v: str) -> str:
        """Ensure the DDS implementation is supported."""
        supported = {"fastdds", "cyclonedds"}
        key = v.strip().lower()
        if key not in supported:
            raise ValueError(
                f"Unsupported dds_implementation '{v}'. Must be one of: {supported}"
            )
        return key
```
(`field_validator` is already imported at the top of `models.py`.)

- [ ] **Step 4: Parse `<dds_implementation>` in the requirements parser**

In `src/dds_optimizer/requirements/parser.py`, inside `parse_requirements`, after `root` is validated and before/with the other section parses, read the field and pass it to the constructor. Add after `xml_dir = ...`:
```python
    dds_implementation = _get_text(root, "dds_implementation", default="fastdds")
```
Then update the final `return RequirementsConfig(...)` to include:
```python
    return RequirementsConfig(
        benchmark=benchmark,
        performance_requirements=performance_requirements,
        optimization_settings=optimization_settings,
        llm_config=llm_config,
        dds_implementation=dds_implementation,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_requirements_parser.py -v 2>&1 | tail -25
```
Expected: all pass, including the three new tests.

- [ ] **Step 6: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: parse and validate <dds_implementation> selection field

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Parameterize the deployer env var

**Files:**
- Modify: `src/dds_optimizer/config/deployer.py`
- Test: `tests/unit/test_deployer.py` (new)

Add optional `env_var` parameters so the deployer can set `CYCLONEDDS_URI` as well as `FASTRTPS_DEFAULT_PROFILES_FILE`, defaulting to the FastDDS var for backward compatibility.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deployer.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Tests for the parameterized config deployer env-var handling."""

from pathlib import Path

from dds_optimizer.config import deployer


def test_build_env_defaults_to_fastdds(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<dds/>")
    env = deployer.build_env_for_subprocess(cfg)
    assert env["FASTRTPS_DEFAULT_PROFILES_FILE"] == str(cfg.resolve())


def test_build_env_uses_custom_var(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<CycloneDDS/>")
    env = deployer.build_env_for_subprocess(cfg, env_var="CYCLONEDDS_URI")
    assert env["CYCLONEDDS_URI"] == str(cfg.resolve())


def test_get_export_command_custom_var(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<CycloneDDS/>")
    cmd = deployer.get_export_command(cfg, env_var="CYCLONEDDS_URI")
    assert cmd.startswith("export CYCLONEDDS_URI=")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_deployer.py -v 2>&1 | tail -20
```
Expected: FAIL — `build_env_for_subprocess() got an unexpected keyword argument 'env_var'`.

- [ ] **Step 3: Add `env_var` params to deployer functions**

In `src/dds_optimizer/config/deployer.py`, update `build_env_for_subprocess` and `get_export_command` to accept an `env_var` parameter defaulting to the module constant. Replace those two functions' signatures/bodies:
```python
def build_env_for_subprocess(
    config_path: Path, env_var: str = FASTDDS_PROFILES_ENV_VAR
) -> dict:
    """Build an environment dict for subprocess calls with the config var set."""
    env = os.environ.copy()
    env[env_var] = str(config_path.resolve())
    return env
```
```python
def get_export_command(
    config_path: Path, env_var: str = FASTDDS_PROFILES_ENV_VAR
) -> str:
    """Generate a shell export command for manual use."""
    return f"export {env_var}={config_path.resolve()}"
```
(Leave `set_fastdds_config`/`restore_previous_config`/`get_current_config` as-is — the loop uses the subprocess-env path, not the process-global setter.)

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_deployer.py -v 2>&1 | tail -20
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: parameterize deployer env var for CycloneDDS_URI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Benchmark launcher — per-backend env var + RMW_IMPLEMENTATION

**Files:**
- Modify: `src/dds_optimizer/benchmark/launcher.py`
- Test: `tests/unit/test_benchmark_env.py` (new)

The launcher currently hardcodes `FASTRTPS_DEFAULT_PROFILES_FILE` in `_build_benchmark_env`. It must instead set the backend's profiles env var **and** `RMW_IMPLEMENTATION` (without which CycloneDDS never reads the config). Rename the config param to a vendor-neutral name.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_benchmark_env.py`:
```python
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""The benchmark subprocess env must carry the backend's profiles var + RMW."""

from pathlib import Path

from dds_optimizer.benchmark.launcher import _build_benchmark_env


def test_env_sets_cyclonedds_var_and_rmw(tmp_path):
    cfg = tmp_path / "c.xml"
    cfg.write_text("<CycloneDDS/>")
    env = _build_benchmark_env(
        config_path=cfg,
        log_folder=tmp_path,
        log_file_name="benchmark_result",
        profiles_env_var="CYCLONEDDS_URI",
        rmw_implementation="rmw_cyclonedds_cpp",
    )
    assert env["CYCLONEDDS_URI"] == str(cfg.resolve())
    assert env["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"
    assert env["ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER"] == str(tmp_path.resolve())
    assert env["ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME"] == "benchmark_result"


def test_env_sets_fastdds_var_and_rmw(tmp_path):
    cfg = tmp_path / "f.xml"
    cfg.write_text("<dds/>")
    env = _build_benchmark_env(
        config_path=cfg,
        log_folder=tmp_path,
        log_file_name="benchmark_result",
        profiles_env_var="FASTRTPS_DEFAULT_PROFILES_FILE",
        rmw_implementation="rmw_fastrtps_cpp",
    )
    assert env["FASTRTPS_DEFAULT_PROFILES_FILE"] == str(cfg.resolve())
    assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_benchmark_env.py -v 2>&1 | tail -20
```
Expected: FAIL — `_build_benchmark_env()` signature mismatch (`unexpected keyword argument 'profiles_env_var'`).

- [ ] **Step 3: Rewrite `_build_benchmark_env`**

In `src/dds_optimizer/benchmark/launcher.py`, replace `_build_benchmark_env` with:
```python
def _build_benchmark_env(
    config_path: Path,
    log_folder: Path,
    log_file_name: str,
    profiles_env_var: str = "FASTRTPS_DEFAULT_PROFILES_FILE",
    rmw_implementation: str = "rmw_fastrtps_cpp",
) -> dict:
    """
    Build the environment dictionary for the benchmark subprocess.

    Sets:
    - <profiles_env_var>: DDS config file the vendor reads
      (FASTRTPS_DEFAULT_PROFILES_FILE or CYCLONEDDS_URI)
    - RMW_IMPLEMENTATION: the RMW ROS2 must use (essential for CycloneDDS to
      read the config at all)
    - ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER / _FILE_NAME: result location
    """
    env = os.environ.copy()
    env[profiles_env_var] = str(config_path.resolve())
    env["RMW_IMPLEMENTATION"] = rmw_implementation
    env[ROS2_BENCHMARK_LOG_FOLDER_ENV] = str(log_folder.resolve())
    env[ROS2_BENCHMARK_LOG_FILE_ENV] = log_file_name
    return env
```

- [ ] **Step 4: Thread backend params through `run_benchmark`**

In `run_benchmark`, rename the parameter `fastdds_config_path` → `config_path` and add two params `profiles_env_var` and `rmw_implementation`. Update the signature:
```python
def run_benchmark(
    benchmark_config: BenchmarkConfig,
    config_path: Path,
    epoch_dir: Path,
    iteration: int,
    profiles_env_var: str = "FASTRTPS_DEFAULT_PROFILES_FILE",
    rmw_implementation: str = "rmw_fastrtps_cpp",
    timeout: int = DEFAULT_BENCHMARK_TIMEOUT,
) -> Tuple[Path, Optional[PipelineTopology]]:
```
Inside the body, replace all uses of `fastdds_config_path` with `config_path` (the existence check, the log line `f"  FastDDS config: {config_path}"` → `f"  DDS config: {config_path}"`, and the `_build_benchmark_env(...)` call). Update the `_build_benchmark_env` call to:
```python
    env = _build_benchmark_env(
        config_path=config_path,
        log_folder=epoch_dir,
        log_file_name=result_filename,
        profiles_env_var=profiles_env_var,
        rmw_implementation=rmw_implementation,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/test_benchmark_env.py -v 2>&1 | tail -20
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: benchmark launcher sets per-backend profiles var + RMW_IMPLEMENTATION

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Wire the backend through the optimization loop

**Files:**
- Modify: `src/dds_optimizer/optimizer/optimization_loop.py`
- Modify: `src/dds_optimizer/utils/file_utils.py` (`get_config_path` filename → `dds_config.xml`)
- Test: `tests/unit/test_optimization_loop.py` must still pass (adjust any call-site expectations)

- [ ] **Step 1: Make the epoch config filename vendor-neutral**

In `src/dds_optimizer/utils/file_utils.py`, change `get_config_path` return line and docstring from `fastdds_config.xml` to `dds_config.xml`:
```python
    return get_epoch_dir(session_dir, iteration) / "dds_config.xml"
```

- [ ] **Step 2: Resolve the backend once and route generation through it**

In `src/dds_optimizer/optimizer/optimization_loop.py`:

Add imports near the other `..` imports:
```python
from ..backends.registry import get_backend
```
Remove the now-unused direct generator import if present (`from ..config.generator import generate_fastdds_config`) — the backend owns generation now.

In `_run_optimization_loop`, right after reading `max_iterations`/`convergence_threshold`, resolve the backend:
```python
    backend = get_backend(requirements.dds_implementation)
    logger.info(f"DDS backend: {backend.name} (RMW: {backend.rmw_implementation})")
```

Replace the epoch 2+ generation call:
```python
            generate_fastdds_config(
                DDSParameterSet(parameters=current_config_params),
                config_path,
            )
```
with:
```python
            backend.generate_config(dict(current_config_params), config_path)
```
(You may drop the now-unused `DDSParameterSet` import if nothing else uses it — check first with grep; the loop no longer constructs it here.)

- [ ] **Step 3: Pass backend env vars into `run_benchmark`**

Update the `run_benchmark(...)` call in `_run_optimization_loop` to use the renamed param and pass backend env info:
```python
            result_json_path, pipeline_topology = run_benchmark(
                benchmark_config=requirements.benchmark,
                config_path=config_path,
                epoch_dir=epoch_dir,
                iteration=iteration,
                profiles_env_var=backend.profiles_env_var,
                rmw_implementation=backend.rmw_implementation,
            )
```

- [ ] **Step 4: Thread backend into the LLM prompt path**

In `_generate_config_with_llm`, add a `backend` parameter and pass it to `build_feedback_prompt`. Update the call in `_run_optimization_loop` to pass `backend=backend`, and add `backend` to `_generate_config_with_llm`'s signature. In the `build_feedback_prompt(...)` call inside `_generate_config_with_llm`, add:
```python
                backend=backend,
```

- [ ] **Step 5: Fix the final "To use" export line to be backend-aware**

In `_print_optimization_summary`, the function has access to `requirements`. Resolve the backend's export var for the closing hint. Replace the hardcoded export block:
```python
        lines.append(
            f"\n  To use:\n"
            f"    export FASTRTPS_DEFAULT_PROFILES_FILE={session.final_config_path}"
        )
```
with:
```python
        backend = get_backend(requirements.dds_implementation)
        lines.append(
            f"\n  To use:\n"
            f"    export {backend.profiles_env_var}={session.final_config_path}"
        )
```

- [ ] **Step 6: Run the loop tests + full suite**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/ -q 2>&1 | tail -25
```
Expected: all pass. If `test_optimization_loop.py` mocks `run_benchmark`/`generate_fastdds_config` with the old names, update those mock targets/signatures to `config_path` and `backend.generate_config` accordingly (adjust the test to patch `dds_optimizer.optimizer.optimization_loop.get_backend` or the backend method as needed), then re-run.

- [ ] **Step 7: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "feat: route config generation, benchmark env, and prompt through DDS backend

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: CLI/main + docs polish

**Files:**
- Modify: `src/dds_optimizer/main.py` (`cmd_run` export hint)
- Modify: `README.md`, `example/README.md`
- Create: `example/cyclonedds_config.xml`
- Modify: `data/templates/user_requirements_template.xml` (add `<dds_implementation>` doc)

- [ ] **Step 1: Make the `cmd_run` success hint backend-aware**

In `src/dds_optimizer/main.py`, `cmd_run` prints `export FASTRTPS_DEFAULT_PROFILES_FILE=...`. Make it reflect the actual backend. After a successful `session`, derive the export var from the parsed requirements. Replace both `export FASTRTPS_DEFAULT_PROFILES_FILE=...` print lines with a computed variable:
```python
        from .backends.registry import get_backend
        export_var = "FASTRTPS_DEFAULT_PROFILES_FILE"
        if session.requirements is not None:
            export_var = get_backend(session.requirements.dds_implementation).profiles_env_var
```
and use `export_var` in the printed export command(s):
```python
            print(f"  export {export_var}={session.final_config_path}")
```

- [ ] **Step 2: Provide a CycloneDDS example initial config**

Copy the reference config into `example/`:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && cp cyclonedds-config-summary/cyclonedds_config.xml example/cyclonedds_config.xml && head -6 example/cyclonedds_config.xml
```
Expected: the `<CycloneDDS ...>` header prints.

- [ ] **Step 3: Document `<dds_implementation>` in the template**

In `data/templates/user_requirements_template.xml`, add near the top (just inside `<optimization_requirements>`), a documented field:
```xml
    <!--
        DDS implementation to optimize: "fastdds" (default) or "cyclonedds".
        Selects the backend, knowledge base, config generator, and RMW.
    -->
    <dds_implementation>fastdds</dds_implementation>
```
(Verify the template path exists first: `ls data/templates/`. If the file name differs, apply the same edit to the actual template file.)

- [ ] **Step 4: Update README command names**

In `README.md` and `example/README.md`, replace `uv run fastdds-optimizer` with `uv run dds-optimizer` everywhere, and add one line noting CycloneDDS is now supported via `<dds_implementation>cyclonedds</dds_implementation>`. Run to confirm no stale command names remain:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && grep -rn "fastdds-optimizer" README.md example/README.md scripts | cat
```
Expected: no matches.

- [ ] **Step 5: Update `scripts/test_all_components.sh` import name check**

The script's `[1/6]` step imports the package and `[3/6]`/`[4/6]` reference it. Confirm they were rewritten in Task 1 Step 3 (`dds_optimizer`). Re-verify:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && grep -n "dds_optimizer\|fastdds_optimizer" scripts/test_all_components.sh | cat
```
Expected: only `dds_optimizer` references (the `[4/6]` config-generator block still imports `dds_optimizer.config.generator` — that path is retained and valid).

- [ ] **Step 6: Commit**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "docs: update CLI name to dds-optimizer, document CycloneDDS selection

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Full-suite verification + end-to-end smoke tests

**Files:** none (verification only)

- [ ] **Step 1: Run the complete unit suite**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run pytest tests/unit/ -v 2>&1 | tail -40
```
Expected: ALL tests pass — original 9 files (post-rename) plus the new ones: `test_backend_base`, `test_cyclonedds_generator`, `test_cyclonedds_validator`, `test_backend_registry`, `test_prompt_builder_backend`, `test_deployer`, `test_benchmark_env`, and the requirements-parser additions.

- [ ] **Step 2: Run the component script**

Run:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && ./scripts/test_all_components.sh 2>&1 | tail -30
```
Expected: "All component tests PASSED!" (the `[1/6]` import now uses `dds_optimizer`).

- [ ] **Step 3: End-to-end CycloneDDS config generation smoke test (no LLM)**

Verify a CycloneDDS run can generate + validate a config purely from the backend, using the real KB defaults:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && uv run python -c "
from pathlib import Path
from dds_optimizer.backends.registry import get_backend
b = get_backend('cyclonedds')
out = Path('/tmp/e2e_cyclone.xml')
b.generate_config({'ack_delay':'5 ms','socket_receive_buffer_size':'8 MiB','max_message_size':'65500B'}, out)
print('validate warnings:', b.validate_config(out))
print(out.read_text())
"
```
Expected: `validate warnings: []` and XML with `<Domain Id="any">`, an `<Internal>` containing `<AckDelay>5 ms</AckDelay>` and `<SocketReceiveBufferSize min="8 MiB"/>`, and `<General><MaxMessageSize>65500B</MaxMessageSize></General>`.

- [ ] **Step 4: (Optional, requires OpenRouter key) Full optimizer dry-run selection check**

This confirms the loop selects the CycloneDDS backend end-to-end. It needs `LLM_API_KEY` (the user will provide) and a real ROS2 + ros2_benchmark environment for the benchmark subprocess. If the benchmark environment is not available, this step validates only that backend selection + prompt building run before the benchmark call.

Set the key and run with a CycloneDDS requirements file (create a temp requirements XML with `<dds_implementation>cyclonedds</dds_implementation>`, `max_iterations=2`, and the example benchmark). Command template:
```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && export LLM_API_KEY=<provided-key> && uv run dds-optimizer run --requirements <cyclone_requirements.xml> --initial-config example/cyclonedds_config.xml --verbose 2>&1 | tail -40
```
Expected: log shows `DDS backend: cyclonedds (RMW: rmw_cyclonedds_cpp)`. If ros2_benchmark is unavailable, the run will fail at the benchmark step — that is acceptable for this smoke test; the backend-selection log line is the pass criterion. Coordinate with the user for the API key and a suitable benchmark environment before running the full loop.

- [ ] **Step 5: Final commit (if any verification-driven fixes were made)**

```bash
cd /root/nasong/ROS2-DDSConfig-Optimizer && git add -A && git commit -m "test: verify full suite and CycloneDDS end-to-end generation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** Package rename (T1), KB relocation (T2), DDSBackend ABC (T3), CycloneDDS generator (T4) incl. element/@attr/shared-parent/sparse/`Id="any"`/verbatim, CycloneDDS validator (T5), registry + concrete backends + FastDDS wrap (T6), prompt builder parameterization (T7), `<dds_implementation>` models+parser (T8), deployer env var (T9), benchmark launcher profiles var + RMW (T10), loop wiring (T11), CLI/main + README + example config + template (T12), testing strategy incl. new test files + suite run (T4–T13). All spec sections mapped.
- **Out-of-scope respected:** no FastDDS generator migration, `cyclonedds_complete_params.json` not wired, no `--dds` CLI flag, no RMW auto-detection, no backward-compat alias.
- **Type consistency:** `DDSBackend.generate_config(params: dict, out_path) -> Path` used identically in T3/T6/T11; FastDDS backend wraps dict → `DDSParameterSet`. `get_backend(name)` used in T6/T11/T12. `run_benchmark(config_path=..., profiles_env_var=..., rmw_implementation=...)` consistent T10/T11. `build_feedback_prompt(..., backend=...)` consistent T7/T11.
- **KB path resolution:** `parents[4]` from `src/dds_optimizer/backends/<vendor>/backend.py` → repo root; verified in T6 Step 6 tests (`knowledge_base_path().exists()`).
