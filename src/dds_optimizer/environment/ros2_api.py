# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""
ROS2 Topology Collector via rclpy APIs (no CLI subprocesses).

Creates a temporary isolated rclpy context, queries the DDS graph directly
using rclpy Node APIs, and returns a structured PipelineTopology.

APIs used (all from rclpy.Node):
  get_node_names_and_namespaces()       → full node list
  get_topic_names_and_types()           → topic list with message types
  get_publishers_info_by_topic(topic)   → publisher node names + QoS profile
  get_subscriptions_info_by_topic(topic)→ subscriber node names
  get_service_names_and_types_by_node() → detect component containers
  create_client() + call_async()        → query component contents (ListNodes)
  create_subscription(..., raw=True)    → measure serialized message sizes
"""

import os
import time
from typing import Dict, List, Optional

from ..models import PipelineTopology, TopicConnection
from ..utils.logger import get_logger

logger = get_logger(__name__)

# ROS2 system topics present in every domain — excluded from pipeline topology
_SYSTEM_TOPICS: frozenset = frozenset({
    "/parameter_events",
    "/rosout",
})

# Infrastructure node patterns — filtered out of the pipeline nodes list.
# Container nodes, launch process nodes, and benchmark-internal namespaces
# add noise without providing optimization-relevant information.
_INFRA_PREFIXES = ("/launch_ros_",)
_INFRA_SUFFIXES = ("_container",)
_INFRA_NAMESPACES = ("/r2b/",)


def _is_infrastructure_node(full_name: str) -> bool:
    """Return True if the node is an infrastructure node (not a pipeline node)."""
    for prefix in _INFRA_PREFIXES:
        if full_name.startswith(prefix):
            return True
    for suffix in _INFRA_SUFFIXES:
        if full_name.endswith(suffix):
            return True
    for ns in _INFRA_NAMESPACES:
        if full_name.startswith(ns):
            return True
    return False


def _make_full_name(name: str, namespace: str) -> str:
    """
    Construct the fully-qualified /namespace/name from the (name, namespace) rclpy tuple.

    rclpy returns the root namespace as '/', so:
      ('publisher', '/')   → '/publisher'
      ('MonitorNode', '/r2b') → '/r2b/MonitorNode'
    """
    return namespace + ("" if namespace.endswith("/") else "/") + name


def collect_pipeline_topology_via_api(
    discovery_timeout_sec: float = 2.0,
    msg_size_timeout_sec: float = 3.0,
) -> PipelineTopology:
    """
    Collect the running ROS2 pipeline topology using rclpy APIs directly.

    Creates a temporary rclpy node in an isolated context (safe to call from
    a background thread), queries the DDS discovery graph, and returns a
    PipelineTopology including:
      - Pipeline nodes (infrastructure nodes filtered out)
      - Topic connections with publisher/subscriber node full paths and QoS
      - Process groups (component containers → hosted nodes)
      - Average serialized message size per topic

    Args:
        discovery_timeout_sec: Seconds to spin before querying, allowing DDS discovery.
        msg_size_timeout_sec: Seconds to collect message samples for size measurement.

    Returns:
        PipelineTopology populated with all available information.

    Raises:
        RuntimeError: If rclpy is not available or initialization fails.
    """
    try:
        import rclpy
    except ImportError as exc:
        raise RuntimeError(
            "rclpy is not available. Make sure a ROS2 workspace is sourced."
        ) from exc

    context = rclpy.Context()
    rclpy.init(context=context)
    try:
        from rclpy.executors import SingleThreadedExecutor
        executor = SingleThreadedExecutor(context=context)
        node = rclpy.create_node(
            f"_dds_optimizer_collector_{os.getpid()}",
            context=context,
            enable_rosout=False,
        )
        executor.add_node(node)
        try:
            return _do_collect(node, executor, discovery_timeout_sec, msg_size_timeout_sec)
        finally:
            executor.remove_node(node)
            node.destroy_node()
            executor.shutdown()
    finally:
        rclpy.shutdown(context=context)


# ---------------------------------------------------------------------------
# Internal collection helpers
# ---------------------------------------------------------------------------

def _spin_for(executor, duration_sec: float) -> None:
    """Spin the executor for `duration_sec` seconds to allow DDS discovery."""
    deadline = time.monotonic() + duration_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.1)


def _do_collect(
    node,
    executor,
    discovery_timeout_sec: float,
    msg_size_timeout_sec: float,
) -> PipelineTopology:
    """Run all collection steps with the given rclpy node and executor."""
    # Allow DDS discovery before querying
    _spin_for(executor, discovery_timeout_sec)

    # All active nodes (full paths, hidden nodes excluded)
    all_names_ns = node.get_node_names_and_namespaces()
    all_nodes = [
        _make_full_name(name, ns)
        for name, ns in all_names_ns
        if not name.startswith("_")
    ]
    pipeline_nodes = [n for n in all_nodes if not _is_infrastructure_node(n)]

    # Topic connections: pub/sub node names + QoS
    topic_connections = _collect_topic_connections(node)

    # Serialized message sizes (best-effort, skipped if no messages arrive)
    if topic_connections:
        _collect_msg_sizes(node, executor, topic_connections, timeout_sec=msg_size_timeout_sec)

    # Process groups: component container → component node list
    process_groups = _collect_process_groups(node, executor, all_nodes)

    logger.info(
        f"API topology: {len(pipeline_nodes)} pipeline nodes, "
        f"{len(topic_connections)} topics, {len(process_groups)} process group(s)"
    )
    return PipelineTopology(
        nodes=pipeline_nodes,
        topics=topic_connections,
        process_groups=process_groups,
    )


def _collect_topic_connections(node) -> List[TopicConnection]:
    """
    Build TopicConnection list using get_publishers_info_by_topic /
    get_subscriptions_info_by_topic.

    These APIs return TopicEndpointInfo objects with full node paths and QoS
    profiles, eliminating the namespace ambiguity present in CLI text output.
    """
    topic_names_and_types = node.get_topic_names_and_types()
    connections: List[TopicConnection] = []

    for topic_name, types in topic_names_and_types:
        if topic_name in _SYSTEM_TOPICS:
            continue

        msg_type = types[0] if types else "unknown"

        pub_infos = node.get_publishers_info_by_topic(topic_name)
        sub_infos = node.get_subscriptions_info_by_topic(topic_name)

        publishers = [
            _make_full_name(info.node_name, info.node_namespace)
            for info in pub_infos
        ]
        subscribers = [
            _make_full_name(info.node_name, info.node_namespace)
            for info in sub_infos
        ]

        # QoS from the first publisher (all publishers on a topic share compatible QoS)
        qos_reliability: Optional[str] = None
        qos_durability: Optional[str] = None
        if pub_infos:
            qos = pub_infos[0].qos_profile
            try:
                qos_reliability = qos.reliability.name
                qos_durability = qos.durability.name
            except AttributeError:
                qos_reliability = str(qos.reliability)
                qos_durability = str(qos.durability)

        connections.append(TopicConnection(
            name=topic_name,
            msg_type=msg_type,
            publishers=publishers,
            subscribers=subscribers,
            qos_reliability=qos_reliability,
            qos_durability=qos_durability,
        ))

    return connections


def _collect_msg_sizes(
    node,
    executor,
    topics: List[TopicConnection],
    timeout_sec: float,
) -> None:
    """
    Subscribe to each topic with raw=True and measure average serialized message size.

    Updates TopicConnection.msg_size_bytes in-place. Skips topics for which
    the message class cannot be imported or no messages arrive within the timeout.
    """
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

    # Permissive QoS that matches any publisher
    recv_qos = QoSProfile(
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
    )

    topic_samples: Dict[str, List[int]] = {}
    subscriptions = []

    for topic in topics:
        try:
            from rosidl_runtime_py.utilities import get_message
            msg_class = get_message(topic.msg_type)
        except (ImportError, LookupError, ModuleNotFoundError) as e:
            logger.debug(f"Cannot import message class for {topic.name} ({topic.msg_type}): {e}")
            continue

        topic_samples[topic.name] = []

        def _make_callback(tname: str):
            def _cb(raw_msg) -> None:
                topic_samples[tname].append(len(raw_msg))
            return _cb

        try:
            sub = node.create_subscription(
                msg_class,
                topic.name,
                _make_callback(topic.name),
                recv_qos,
                raw=True,
            )
            subscriptions.append(sub)
        except Exception as e:
            logger.debug(f"Could not subscribe to {topic.name} for size measurement: {e}")

    # Spin using the shared executor to collect samples
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.05)

    for sub in subscriptions:
        node.destroy_subscription(sub)

    for topic in topics:
        samples = topic_samples.get(topic.name, [])
        if samples:
            topic.msg_size_bytes = round(sum(samples) / len(samples), 1)
            logger.debug(
                f"  {topic.name}: avg msg size = {topic.msg_size_bytes} bytes "
                f"({len(samples)} samples)"
            )


def _collect_process_groups(
    node,
    executor,
    all_nodes: List[str],
) -> Dict[str, List[str]]:
    """
    Identify ROS2 component containers and return a mapping of
    container full name → list of component node full names.

    A node is a component container if it exposes all three services:
      <node>/_container/load_node
      <node>/_container/unload_node
      <node>/_container/list_nodes

    For each confirmed container, calls the ListNodes service to get the
    actual list of loaded components.

    Standalone nodes (not inside any container) are not included in the result;
    the caller can infer they run in their own separate process.
    """
    process_groups: Dict[str, List[str]] = {}

    for full_name in all_nodes:
        # Parse (name, namespace) from full path
        slash_idx = full_name.rfind("/")
        if slash_idx > 0:
            namespace = full_name[:slash_idx]
            name = full_name[slash_idx + 1:]
        else:
            namespace = "/"
            name = full_name.lstrip("/")

        try:
            srv_names_types = node.get_service_names_and_types_by_node(name, namespace)
        except Exception:
            continue

        service_names = {s[0] for s in srv_names_types}
        is_container = (
            any(s.endswith("/_container/load_node") for s in service_names)
            and any(s.endswith("/_container/unload_node") for s in service_names)
            and any(s.endswith("/_container/list_nodes") for s in service_names)
        )
        if not is_container:
            continue

        components = _query_container_nodes(node, executor, full_name)
        if components is not None:
            process_groups[full_name] = components

    return process_groups


def _query_container_nodes(
    node,
    executor,
    container_full_name: str,
) -> Optional[List[str]]:
    """
    Call the _container/list_nodes service and return the component full names.

    Returns None if the service call times out or composition_interfaces is unavailable.
    """
    try:
        import composition_interfaces.srv
    except ImportError:
        logger.debug("composition_interfaces not available; skipping container query")
        return None

    service_name = f"{container_full_name}/_container/list_nodes"
    client = node.create_client(composition_interfaces.srv.ListNodes, service_name)
    try:
        if not client.wait_for_service(timeout_sec=2.0):
            logger.debug(f"ListNodes service not ready for {container_full_name}")
            return None

        future = client.call_async(composition_interfaces.srv.ListNodes.Request())
        executor.spin_until_future_complete(future, timeout_sec=3.0)

        if future.done() and future.result() is not None:
            return list(future.result().full_node_names)

        logger.debug(f"ListNodes call timed out or returned no result for {container_full_name}")
        return None

    except Exception as e:
        logger.debug(f"ListNodes call failed for {container_full_name}: {e}")
        return None
    finally:
        node.destroy_client(client)
