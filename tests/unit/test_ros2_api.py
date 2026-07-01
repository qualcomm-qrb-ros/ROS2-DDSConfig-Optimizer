# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for ros2_api.py — all rclpy calls are mocked."""

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from dds_optimizer.environment.ros2_api import (
    _collect_process_groups,
    _collect_topic_connections,
    _is_infrastructure_node,
    _make_full_name,
)
from dds_optimizer.models import TopicConnection


# ---------------------------------------------------------------------------
# _make_full_name
# ---------------------------------------------------------------------------

class TestMakeFullName:
    def test_root_namespace(self):
        assert _make_full_name("publisher", "/") == "/publisher"

    def test_nested_namespace(self):
        assert _make_full_name("MonitorNode", "/r2b") == "/r2b/MonitorNode"

    def test_trailing_slash_namespace(self):
        assert _make_full_name("foo", "/ns/") == "/ns/foo"


# ---------------------------------------------------------------------------
# _is_infrastructure_node
# ---------------------------------------------------------------------------

class TestIsInfrastructureNode:
    @pytest.mark.parametrize("full_name", [
        "/launch_ros_12345",
        "/launch_ros_abc",
        "/publisher_container",
        "/subscriber_monitor_container",
        "/r2b/MonitorNode",
        "/r2b/SomeHelper",
    ])
    def test_infrastructure_nodes_filtered(self, full_name):
        assert _is_infrastructure_node(full_name) is True

    @pytest.mark.parametrize("full_name", [
        "/publisher",
        "/subscriber",
        "/camera_node",
        "/lidar_processor",
    ])
    def test_pipeline_nodes_kept(self, full_name):
        assert _is_infrastructure_node(full_name) is False


# ---------------------------------------------------------------------------
# _collect_topic_connections
# ---------------------------------------------------------------------------

def _make_endpoint_info(node_name, namespace, qos_reliability="RELIABLE", qos_durability="VOLATILE"):
    """Build a mock TopicEndpointInfo."""
    info = MagicMock()
    info.node_name = node_name
    info.node_namespace = namespace
    qos = MagicMock()
    qos.reliability.name = qos_reliability
    qos.durability.name = qos_durability
    info.qos_profile = qos
    return info


class TestCollectTopicConnections:
    def _make_node(self, topics, pub_map, sub_map):
        node = MagicMock()
        node.get_topic_names_and_types.return_value = topics
        node.get_publishers_info_by_topic.side_effect = lambda t: pub_map.get(t, [])
        node.get_subscriptions_info_by_topic.side_effect = lambda t: sub_map.get(t, [])
        return node

    def test_system_topics_excluded(self):
        node = self._make_node(
            topics=[("/parameter_events", ["rcl_interfaces/msg/ParameterEvent"]),
                    ("/rosout", ["rcl_interfaces/msg/Log"]),
                    ("/counter", ["std_msgs/msg/Header"])],
            pub_map={"/counter": [_make_endpoint_info("publisher", "/")]},
            sub_map={"/counter": [_make_endpoint_info("subscriber", "/")]},
        )
        result = _collect_topic_connections(node)
        assert len(result) == 1
        assert result[0].name == "/counter"

    def test_full_node_paths_constructed(self):
        node = self._make_node(
            topics=[("/counter", ["std_msgs/msg/Header"])],
            pub_map={"/counter": [_make_endpoint_info("publisher", "/")]},
            sub_map={"/counter": [_make_endpoint_info("MonitorNode", "/r2b")]},
        )
        result = _collect_topic_connections(node)
        assert result[0].publishers == ["/publisher"]
        assert result[0].subscribers == ["/r2b/MonitorNode"]

    def test_qos_extracted(self):
        node = self._make_node(
            topics=[("/counter", ["std_msgs/msg/Header"])],
            pub_map={"/counter": [_make_endpoint_info("publisher", "/",
                                                       qos_reliability="RELIABLE",
                                                       qos_durability="VOLATILE")]},
            sub_map={"/counter": []},
        )
        result = _collect_topic_connections(node)
        assert result[0].qos_reliability == "RELIABLE"
        assert result[0].qos_durability == "VOLATILE"

    def test_msg_type_from_first_type(self):
        node = self._make_node(
            topics=[("/counter", ["std_msgs/msg/Header", "other/type"])],
            pub_map={"/counter": []},
            sub_map={"/counter": []},
        )
        result = _collect_topic_connections(node)
        assert result[0].msg_type == "std_msgs/msg/Header"

    def test_empty_topic_list(self):
        node = self._make_node(topics=[], pub_map={}, sub_map={})
        assert _collect_topic_connections(node) == []


# ---------------------------------------------------------------------------
# _collect_process_groups
# ---------------------------------------------------------------------------

class TestCollectProcessGroups:
    def _make_container_node(self, container_full_name: str):
        """Mock a rclpy node that sees one container."""
        node = MagicMock()
        executor = MagicMock()

        slash_idx = container_full_name.rfind("/")
        ns = container_full_name[:slash_idx] if slash_idx > 0 else "/"
        name = container_full_name[slash_idx + 1:]

        container_services = [
            (f"{container_full_name}/_container/load_node",
             ["composition_interfaces/srv/LoadNode"]),
            (f"{container_full_name}/_container/unload_node",
             ["composition_interfaces/srv/UnloadNode"]),
            (f"{container_full_name}/_container/list_nodes",
             ["composition_interfaces/srv/ListNodes"]),
        ]

        def get_services(node_name, node_ns):
            if node_name == name and node_ns == ns:
                return container_services
            return []

        node.get_service_names_and_types_by_node.side_effect = get_services
        return node, executor

    def test_no_containers(self):
        node = MagicMock()
        executor = MagicMock()
        node.get_service_names_and_types_by_node.return_value = []
        result = _collect_process_groups(node, executor, ["/publisher", "/subscriber"])
        assert result == {}

    def test_exception_in_service_query_is_skipped(self):
        node = MagicMock()
        executor = MagicMock()
        node.get_service_names_and_types_by_node.side_effect = Exception("RCL error")
        result = _collect_process_groups(node, executor, ["/publisher"])
        assert result == {}

    def test_container_identified_by_services(self):
        """A node with all three container services should be identified."""
        node, executor = self._make_container_node("/publisher_container")
        with patch(
            "dds_optimizer.environment.ros2_api._query_container_nodes",
            return_value=["/publisher"],
        ):
            result = _collect_process_groups(
                node, executor, ["/publisher_container", "/publisher"]
            )
        assert result == {"/publisher_container": ["/publisher"]}

    def test_query_returning_none_skipped(self):
        node, executor = self._make_container_node("/pub_container")
        with patch(
            "dds_optimizer.environment.ros2_api._query_container_nodes",
            return_value=None,
        ):
            result = _collect_process_groups(node, executor, ["/pub_container"])
        assert result == {}


# ---------------------------------------------------------------------------
# collector.py fallback behaviour (regression: logger NameError)
# ---------------------------------------------------------------------------

class TestCollectorFallback:
    """
    Verify that collect_pipeline_topology() in collector.py:
    1. Falls back to CLI when the rclpy API raises any exception
    2. Does NOT itself raise a secondary NameError (logger must be defined)
    """

    def test_fallback_to_cli_on_api_failure(self):
        """When rclpy API raises, CLI fallback is used and no NameError propagates."""
        from dds_optimizer.environment import collector

        empty_topology = collector.PipelineTopology(nodes=[], topics=[])

        # Patch at the source module since collector uses a lazy import
        with patch(
            "dds_optimizer.environment.ros2_api.collect_pipeline_topology_via_api",
            side_effect=RuntimeError("rclpy not available"),
        ), patch(
            "dds_optimizer.environment.collector._collect_pipeline_topology_via_cli",
            return_value=empty_topology,
        ) as mock_cli:
            result = collector.collect_pipeline_topology()

        mock_cli.assert_called_once()
        assert result is empty_topology

    def test_logger_defined_in_collector(self):
        """Ensure collector module has a logger so the except block never raises NameError."""
        from dds_optimizer.environment import collector
        assert hasattr(collector, "logger"), "collector.logger must be defined at module level"

    def test_api_exception_does_not_propagate(self):
        """Any exception from the rclpy API path must be caught, not re-raised."""
        from dds_optimizer.environment import collector

        with patch(
            "dds_optimizer.environment.ros2_api.collect_pipeline_topology_via_api",
            side_effect=Exception("unexpected error from rclpy"),
        ), patch(
            "dds_optimizer.environment.collector._collect_pipeline_topology_via_cli",
            return_value=collector.PipelineTopology(),
        ):
            # Must not raise
            result = collector.collect_pipeline_topology()
        assert isinstance(result, collector.PipelineTopology)
