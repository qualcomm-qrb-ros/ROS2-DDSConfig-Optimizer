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
