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
  6. Value validation — the LLM occasionally emits a semantically-invalid value
     (e.g. "A" for a boolean field). CycloneDDS rejects the whole config if any
     value is invalid, which would fail the entire benchmark epoch. To stay
     robust we validate the value against the KB `type` and skip (with a
     warning) any parameter whose value is clearly invalid, so the remaining
     valid parameters still produce a usable config. Only reliable checks are
     applied: `int` (parseable + within min/max) and `bool` (true/false). String,
     enum, and list types are passed through unchecked because their KB
     `possible_values` are unreliable and legal values include unit-suffixed
     strings like "8 MiB" and "default".
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

from ...utils.logger import get_logger

logger = get_logger(__name__)

CYCLONEDDS_NAMESPACE = "https://cdds.io/config"

# Accepted boolean spellings for bool-typed parameters (case-insensitive).
_BOOL_TOKENS = {"true", "false"}


def _str(value) -> str:
    """XML string form; bools lowercased to match CycloneDDS conventions."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _is_valid_value(name: str, value, info: Dict) -> bool:
    """
    Check an LLM-supplied value against the KB type before writing it.

    Only reliable checks are enforced (see the module docstring):
    - int:  must parse as an integer and lie within [min, max] when given.
    - bool: must be a real bool or the string 'true'/'false' (case-insensitive).
    Other types (string/enum/list) are always accepted here — their legal values
    are not reliably enumerable in the KB.

    Returns True if the value is acceptable, False if it should be skipped.
    """
    param_type = info.get("type")

    if param_type == "bool":
        if isinstance(value, bool):
            return True
        if isinstance(value, str) and value.strip().lower() in _BOOL_TOKENS:
            return True
        logger.warning(
            f"CycloneDDS param '{name}': invalid bool value {value!r} "
            "(expected true/false); skipping."
        )
        return False

    if param_type == "int":
        # bool is a subclass of int but is not a valid integer value here.
        if isinstance(value, bool):
            logger.warning(
                f"CycloneDDS param '{name}': expected int, got bool {value!r}; skipping."
            )
            return False
        try:
            ivalue = int(str(value).strip())
        except (TypeError, ValueError):
            logger.warning(
                f"CycloneDDS param '{name}': invalid int value {value!r}; skipping."
            )
            return False
        lo = info.get("min")
        hi = info.get("max")
        if isinstance(lo, (int, float)) and ivalue < lo:
            logger.warning(
                f"CycloneDDS param '{name}': int {ivalue} below min {lo}; skipping."
            )
            return False
        if isinstance(hi, (int, float)) and ivalue > hi:
            logger.warning(
                f"CycloneDDS param '{name}': int {ivalue} above max {hi}; skipping."
            )
            return False
        return True

    # string / enum / list and any unknown type: pass through unchecked.
    return True


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
        if not _is_valid_value(name, value, info):
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
