# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
Config Generator: generates FastDDS XML configuration files from LLM parameter values.

The generator takes a DDSParameterSet (from the LLM response parser) and produces
a complete, valid FastDDS XML configuration file by programmatically building the
XML structure using Python's xml.etree.ElementTree.

This approach is more robust than string templating because:
1. It always produces well-formed XML
2. Parameter values are properly escaped
3. The structure is guaranteed to be correct

The generated XML follows the FastDDS XML profile format:
https://fast-dds.docs.eprosima.com/en/latest/fastdds/xml_configuration/xml_configuration.html
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

from ..models import DDSParameterSet
from ..utils.logger import get_logger

logger = get_logger(__name__)


# Mapping from knowledge-base memory policy names to FastDDS XML values.
# The knowledge base uses the C++ enum names (e.g. PREALLOCATED_MEMORY_MODE),
# but the FastDDS XML parser expects the shorter XML token (e.g. PREALLOCATED).
_MEMORY_POLICY_MAP: Dict[str, str] = {
    "PREALLOCATED_MEMORY_MODE": "PREALLOCATED",
    "PREALLOCATED_WITH_REALLOC_MEMORY_MODE": "PREALLOCATED_WITH_REALLOC",
    "DYNAMIC_RESERVE_MEMORY_MODE": "DYNAMIC",
    "DYNAMIC_REUSABLE_MEMORY_MODE": "DYNAMIC_REUSABLE",
}


def _str(value: Any) -> str:
    """Convert a value to its XML string representation."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _memory_policy(value: Any, default: str = "PREALLOCATED_WITH_REALLOC") -> str:
    """
    Convert a memory policy value to the FastDDS XML token.

    Accepts both the C++ enum name (PREALLOCATED_MEMORY_MODE) and the
    XML token (PREALLOCATED) and always returns the XML token.
    """
    s = str(value)
    return _MEMORY_POLICY_MAP.get(s, s)


def generate_fastdds_config(
    param_set: DDSParameterSet,
    output_path: Path,
) -> Path:
    """
    Generate a FastDDS XML configuration file from a set of parameter values.

    This function builds the complete XML structure programmatically and writes
    it to the specified output path.

    Args:
        param_set: Validated DDS parameter values from the LLM.
        output_path: Path where the XML file should be written.

    Returns:
        Path to the generated XML file (same as output_path).

    Example:
        >>> params = DDSParameterSet(parameters={"history_depth": 10, ...})
        >>> path = generate_fastdds_config(params, Path("/tmp/fastdds.xml"))
        >>> print(path)
        /tmp/fastdds.xml
    """
    p = param_set.parameters

    # Helper to get a parameter value with a fallback default
    def get(key: str, default: Any = None) -> Any:
        return p.get(key, default)

    # -----------------------------------------------------------------------
    # Root element
    # -----------------------------------------------------------------------
    root = ET.Element("dds")

    # -----------------------------------------------------------------------
    # Transport Descriptors
    # -----------------------------------------------------------------------
    profiles = ET.SubElement(root, "profiles")
    transport_descriptors = ET.SubElement(profiles, "transport_descriptors")

    # --- UDP Transport ---
    udp_td = ET.SubElement(transport_descriptors, "transport_descriptor")
    ET.SubElement(udp_td, "transport_id").text = "OptimizedUDPv4"
    ET.SubElement(udp_td, "type").text = "UDPv4"
    ET.SubElement(udp_td, "sendBufferSize").text = _str(get("udp_send_buffer_size", 0))
    ET.SubElement(udp_td, "receiveBufferSize").text = _str(get("udp_receive_buffer_size", 0))
    ET.SubElement(udp_td, "maxMessageSize").text = _str(get("udp_max_message_size", 65500))
    ET.SubElement(udp_td, "non_blocking_send").text = _str(get("udp_non_blocking_send", False))

    # --- SHM Transport ---
    shm_max_msg_size = int(get("shm_max_message_size", 524288))
    shm_seg_size = int(get("shm_segment_size", 262144))

    # FastDDS constraint: segment_size must be >= maxMessageSize.
    # Silently correct when the LLM (or defaults) violate this invariant so
    # the participant can at least register the SHM transport.
    if shm_seg_size < shm_max_msg_size:
        corrected = shm_max_msg_size * 4
        logger.warning(
            f"shm_segment_size ({shm_seg_size}) < shm_max_message_size ({shm_max_msg_size}). "
            f"Auto-correcting shm_segment_size to {corrected} (4x max message size)."
        )
        shm_seg_size = corrected

    shm_td = ET.SubElement(transport_descriptors, "transport_descriptor")
    ET.SubElement(shm_td, "transport_id").text = "OptimizedSHM"
    ET.SubElement(shm_td, "type").text = "SHM"
    ET.SubElement(shm_td, "maxMessageSize").text = str(shm_max_msg_size)
    ET.SubElement(shm_td, "segment_size").text = str(shm_seg_size)
    ET.SubElement(shm_td, "port_queue_capacity").text = _str(get("shm_port_queue_capacity", 512))

    # -----------------------------------------------------------------------
    # Participant Profile
    # -----------------------------------------------------------------------
    participant = ET.SubElement(profiles, "participant")
    participant.set("profile_name", "optimized_participant")
    participant.set("is_default_profile", "true")

    ET.SubElement(participant, "domainId").text = "0"

    rtps = ET.SubElement(participant, "rtps")
    ET.SubElement(rtps, "name").text = "OptimizedParticipant"
    ET.SubElement(rtps, "sendSocketBufferSize").text = _str(
        get("participant_send_socket_buffer", 0)
    )
    ET.SubElement(rtps, "listenSocketBufferSize").text = _str(
        get("participant_listen_socket_buffer", 0)
    )

    # Builtin discovery
    builtin = ET.SubElement(rtps, "builtin")
    discovery_config = ET.SubElement(builtin, "discovery_config")

    lease_duration = ET.SubElement(discovery_config, "leaseDuration")
    ET.SubElement(lease_duration, "sec").text = _str(get("lease_duration_sec", 20))

    lease_announcement = ET.SubElement(discovery_config, "leaseAnnouncement")
    ET.SubElement(lease_announcement, "sec").text = _str(get("lease_announcement_sec", 3))
    ET.SubElement(lease_announcement, "nanosec").text = _str(
        get("lease_announcement_nanosec", 0)
    )

    initial_announcements = ET.SubElement(discovery_config, "initialAnnouncements")
    ET.SubElement(initial_announcements, "count").text = _str(
        get("initial_announcements_count", 5)
    )
    ia_period = ET.SubElement(initial_announcements, "period")
    ET.SubElement(ia_period, "nanosec").text = _str(
        get("initial_announcements_period_nanosec", 100000000)
    )

    # Memory policies for builtin endpoints
    ET.SubElement(builtin, "readerHistoryMemoryPolicy").text = _memory_policy(
        get("reader_history_memory_policy", "PREALLOCATED_WITH_REALLOC_MEMORY_MODE")
    )
    ET.SubElement(builtin, "writerHistoryMemoryPolicy").text = _memory_policy(
        get("writer_history_memory_policy", "PREALLOCATED_WITH_REALLOC_MEMORY_MODE")
    )

    # Allocation settings
    allocation = ET.SubElement(rtps, "allocation")

    remote_locators = ET.SubElement(allocation, "remote_locators")
    ET.SubElement(remote_locators, "max_unicast_locators").text = _str(
        get("max_unicast_locators", 4)
    )
    ET.SubElement(remote_locators, "max_multicast_locators").text = _str(
        get("max_multicast_locators", 1)
    )

    total_participants = ET.SubElement(allocation, "total_participants")
    ET.SubElement(total_participants, "initial").text = _str(
        get("total_participants_initial", 0)
    )
    ET.SubElement(total_participants, "maximum").text = _str(
        get("total_participants_maximum", 0)
    )

    send_buffers = ET.SubElement(allocation, "send_buffers")
    ET.SubElement(send_buffers, "preallocated_number").text = _str(
        get("send_buffers_preallocated", 0)
    )
    ET.SubElement(send_buffers, "dynamic").text = _str(
        get("send_buffers_dynamic", False)
    )

    # Transport selection
    user_transports = ET.SubElement(rtps, "userTransports")
    ET.SubElement(user_transports, "transport_id").text = "OptimizedUDPv4"
    ET.SubElement(user_transports, "transport_id").text = "OptimizedSHM"
    ET.SubElement(rtps, "useBuiltinTransports").text = "false"

    # -----------------------------------------------------------------------
    # Data Writer Profile
    # -----------------------------------------------------------------------
    data_writer = ET.SubElement(profiles, "data_writer")
    data_writer.set("profile_name", "optimized_writer")
    data_writer.set("is_default_profile", "true")

    # Writer topic settings
    writer_topic = ET.SubElement(data_writer, "topic")
    writer_history_qos = ET.SubElement(writer_topic, "historyQos")
    ET.SubElement(writer_history_qos, "kind").text = _str(get("history_kind", "KEEP_LAST"))
    ET.SubElement(writer_history_qos, "depth").text = _str(get("history_depth", 1))

    writer_resource_limits = ET.SubElement(writer_topic, "resourceLimitsQos")
    ET.SubElement(writer_resource_limits, "max_samples").text = _str(get("max_samples", 5000))
    ET.SubElement(writer_resource_limits, "max_instances").text = "1"
    ET.SubElement(writer_resource_limits, "max_samples_per_instance").text = _str(
        get("max_samples", 5000)
    )
    ET.SubElement(writer_resource_limits, "allocated_samples").text = _str(
        get("allocated_samples", 100)
    )

    # Writer QoS
    writer_qos = ET.SubElement(data_writer, "qos")

    writer_reliability = ET.SubElement(writer_qos, "reliability")
    ET.SubElement(writer_reliability, "kind").text = _str(
        get("reliability_kind", "RELIABLE")
    )
    writer_reliability_blocking = ET.SubElement(writer_reliability, "max_blocking_time")
    ET.SubElement(writer_reliability_blocking, "sec").text = "0"
    ET.SubElement(writer_reliability_blocking, "nanosec").text = "100000000"

    writer_durability = ET.SubElement(writer_qos, "durability")
    ET.SubElement(writer_durability, "kind").text = _str(
        get("durability_kind", "VOLATILE")
    )

    writer_data_sharing = ET.SubElement(writer_qos, "data_sharing")
    ET.SubElement(writer_data_sharing, "kind").text = _str(
        get("data_sharing_kind", "AUTO")
    )

    writer_publish_mode = ET.SubElement(writer_qos, "publishMode")
    ET.SubElement(writer_publish_mode, "kind").text = _str(
        get("publish_mode", "SYNCHRONOUS")
    )

    writer_disable_acks = ET.SubElement(writer_qos, "disablePositiveAcks")
    ET.SubElement(writer_disable_acks, "enabled").text = _str(
        get("disable_positive_acks", False)
    )

    # Writer timing
    writer_times = ET.SubElement(data_writer, "times")

    writer_initial_hb = ET.SubElement(writer_times, "initialHeartbeatDelay")
    ET.SubElement(writer_initial_hb, "nanosec").text = "0"

    writer_hb_period = ET.SubElement(writer_times, "heartbeatPeriod")
    ET.SubElement(writer_hb_period, "sec").text = _str(
        get("writer_heartbeat_period_sec", 0)
    )
    ET.SubElement(writer_hb_period, "nanosec").text = _str(
        get("writer_heartbeat_period_nanosec", 500000000)
    )

    writer_nack_delay = ET.SubElement(writer_times, "nackResponseDelay")
    ET.SubElement(writer_nack_delay, "nanosec").text = _str(
        get("writer_nack_response_delay_nanosec", 5000000)
    )

    # Writer memory policy
    ET.SubElement(data_writer, "historyMemoryPolicy").text = _memory_policy(
        get("writer_history_memory_policy", "PREALLOCATED_WITH_REALLOC_MEMORY_MODE")
    )

    # -----------------------------------------------------------------------
    # Data Reader Profile
    # -----------------------------------------------------------------------
    data_reader = ET.SubElement(profiles, "data_reader")
    data_reader.set("profile_name", "optimized_reader")
    data_reader.set("is_default_profile", "true")

    # Reader topic settings
    reader_topic = ET.SubElement(data_reader, "topic")
    reader_history_qos = ET.SubElement(reader_topic, "historyQos")
    ET.SubElement(reader_history_qos, "kind").text = _str(get("history_kind", "KEEP_LAST"))
    ET.SubElement(reader_history_qos, "depth").text = _str(get("history_depth", 1))

    reader_resource_limits = ET.SubElement(reader_topic, "resourceLimitsQos")
    ET.SubElement(reader_resource_limits, "max_samples").text = _str(get("max_samples", 5000))
    ET.SubElement(reader_resource_limits, "max_instances").text = "1"
    ET.SubElement(reader_resource_limits, "max_samples_per_instance").text = _str(
        get("max_samples", 5000)
    )
    ET.SubElement(reader_resource_limits, "allocated_samples").text = _str(
        get("allocated_samples", 100)
    )

    # Reader QoS
    reader_qos = ET.SubElement(data_reader, "qos")

    reader_reliability = ET.SubElement(reader_qos, "reliability")
    ET.SubElement(reader_reliability, "kind").text = _str(
        get("reliability_kind", "RELIABLE")
    )

    reader_durability = ET.SubElement(reader_qos, "durability")
    ET.SubElement(reader_durability, "kind").text = _str(
        get("durability_kind", "VOLATILE")
    )

    reader_data_sharing = ET.SubElement(reader_qos, "data_sharing")
    ET.SubElement(reader_data_sharing, "kind").text = _str(
        get("data_sharing_kind", "AUTO")
    )

    # Reader timing
    reader_times = ET.SubElement(data_reader, "times")

    reader_initial_acknack = ET.SubElement(reader_times, "initialAcknackDelay")
    ET.SubElement(reader_initial_acknack, "nanosec").text = _str(
        get("reader_initial_acknack_delay_nanosec", 70000000)
    )

    reader_hb_response = ET.SubElement(reader_times, "heartbeatResponseDelay")
    ET.SubElement(reader_hb_response, "nanosec").text = _str(
        get("reader_heartbeat_response_delay_nanosec", 5000000)
    )

    # Reader memory policy
    ET.SubElement(data_reader, "historyMemoryPolicy").text = _memory_policy(
        get("reader_history_memory_policy", "PREALLOCATED_WITH_REALLOC_MEMORY_MODE")
    )

    # -----------------------------------------------------------------------
    # Library Settings
    # -----------------------------------------------------------------------
    library_settings = ET.SubElement(root, "library_settings")
    ET.SubElement(library_settings, "intraprocess_delivery").text = _str(
        get("intraprocess_delivery", "OFF")
    )

    # -----------------------------------------------------------------------
    # Write XML to file with pretty formatting
    # -----------------------------------------------------------------------
    _indent_xml(root)
    tree = ET.ElementTree(root)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with XML declaration (open in text mode for encoding="unicode")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8" ?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    logger.info(f"Generated FastDDS config: {output_path}")
    return output_path


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    """
    Add pretty-print indentation to an XML element tree in-place.

    Python's xml.etree.ElementTree does not support pretty-printing natively
    in Python < 3.9. This function adds newlines and indentation manually.

    Args:
        elem: Root XML element to indent.
        level: Current indentation level (0 = root).
    """
    indent = "\n" + "    " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "    "
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
        for child in elem:
            _indent_xml(child, level + 1)
        # Fix the last child's tail
        if not child.tail or not child.tail.strip():
            child.tail = indent
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent
    if not level:
        elem.tail = "\n"
