# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear

"""Unit tests for prompt_builder._format_pipeline_topology_section (JSON format)."""

import json

import pytest

from dds_optimizer.llm.prompt_builder import _format_pipeline_topology_section
from dds_optimizer.models import PipelineTopology, TopicConnection


def _make_topic(
    name="/counter",
    msg_type="std_msgs/msg/Header",
    publishers=None,
    subscribers=None,
    msg_size_bytes=None,
    qos_reliability=None,
    qos_durability=None,
):
    return TopicConnection(
        name=name,
        msg_type=msg_type,
        publishers=publishers or [],
        subscribers=subscribers or [],
        msg_size_bytes=msg_size_bytes,
        qos_reliability=qos_reliability,
        qos_durability=qos_durability,
    )


def _parse_json(result: str) -> dict:
    """Extract and parse the JSON block from the topology section."""
    # Strip the '## Pipeline Topology' header and parse the rest as JSON
    lines = result.split("\n", 2)
    json_text = lines[-1].strip()
    return json.loads(json_text)


class TestFormatPipelineTopologySection:

    def test_none_topology(self):
        result = _format_pipeline_topology_section(None)
        assert "Not available" in result
        assert "## Pipeline Topology" in result

    def test_empty_topology(self):
        result = _format_pipeline_topology_section(PipelineTopology())
        assert "No active nodes or topics detected" in result
        assert "## Pipeline Topology" in result

    def test_section_title(self):
        """Title must be '## Pipeline Topology' without the old suffix."""
        topo = PipelineTopology(
            nodes=["/publisher"],
            topics=[_make_topic(publishers=["/publisher"])],
        )
        result = _format_pipeline_topology_section(topo)
        assert result.startswith("## Pipeline Topology\n")
        assert "collected during benchmark" not in result

    def test_node_count_in_pipeline_info(self):
        topo = PipelineTopology(
            nodes=["/publisher", "/subscriber"],
            topics=[_make_topic(publishers=["/publisher"], subscribers=["/subscriber"])],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        assert data["pipeline info"]["number of ros2 nodes"] == 2

    def test_cross_process_true_when_multiple_containers(self):
        topo = PipelineTopology(
            nodes=["/publisher", "/subscriber"],
            topics=[_make_topic(publishers=["/publisher"], subscribers=["/subscriber"])],
            process_groups={
                "/publisher_container": ["/publisher"],
                "/subscriber_container": ["/subscriber"],
            },
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        assert data["pipeline info"]["cross process communication"] is True

    def test_cross_process_false_when_single_container(self):
        topo = PipelineTopology(
            nodes=["/pub", "/sub"],
            topics=[_make_topic(publishers=["/pub"], subscribers=["/sub"])],
            process_groups={"/my_container": ["/pub", "/sub"]},
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        assert data["pipeline info"]["cross process communication"] is False

    def test_cross_process_true_with_standalone(self):
        """One container + one standalone node = 2 processes = cross-process."""
        topo = PipelineTopology(
            nodes=["/publisher", "/subscriber"],
            topics=[_make_topic(publishers=["/publisher"], subscribers=["/subscriber"])],
            process_groups={"/publisher_container": ["/publisher"]},
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        assert data["pipeline info"]["cross process communication"] is True

    def test_cross_process_absent_when_no_process_groups(self):
        """Without process group data the key is omitted."""
        topo = PipelineTopology(
            nodes=["/publisher", "/subscriber"],
            topics=[_make_topic(publishers=["/publisher"], subscribers=["/subscriber"])],
            process_groups={},
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        assert "cross process communication" not in data["pipeline info"]

    def test_published_topic_shown_under_publisher_node(self):
        topo = PipelineTopology(
            nodes=["/publisher", "/subscriber"],
            topics=[_make_topic(
                name="/counter",
                msg_type="std_msgs/msg/Header",
                publishers=["/publisher"],
                subscribers=["/subscriber"],
            )],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        nodes = data["ros2 nodes info"]
        pub_node = next(v for v in nodes.values() if v["node name"] == "/publisher")
        assert "published topics" in pub_node
        t1 = pub_node["published topics"]["topic 1"]
        assert t1["topic name"] == "/counter"
        assert t1["topic type"] == "std_msgs/msg/Header"

    def test_subscribed_topic_shown_under_subscriber_node(self):
        topo = PipelineTopology(
            nodes=["/publisher", "/subscriber"],
            topics=[_make_topic(
                publishers=["/publisher"],
                subscribers=["/subscriber"],
            )],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        nodes = data["ros2 nodes info"]
        sub_node = next(v for v in nodes.values() if v["node name"] == "/subscriber")
        assert "subscribed topics" in sub_node

    def test_qos_reliability_in_published_topic(self):
        topo = PipelineTopology(
            nodes=["/publisher"],
            topics=[_make_topic(
                publishers=["/publisher"],
                qos_reliability="RELIABLE",
            )],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        nodes = data["ros2 nodes info"]
        t1 = list(nodes.values())[0]["published topics"]["topic 1"]
        assert t1["qos reliability"] == "RELIABLE"

    def test_msg_size_in_topic_when_available(self):
        topo = PipelineTopology(
            nodes=["/publisher"],
            topics=[_make_topic(publishers=["/publisher"], msg_size_bytes=64.0)],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        nodes = data["ros2 nodes info"]
        t1 = list(nodes.values())[0]["published topics"]["topic 1"]
        assert t1["avg msg size bytes"] == 64.0

    def test_msg_size_absent_when_not_measured(self):
        topo = PipelineTopology(
            nodes=["/publisher"],
            topics=[_make_topic(publishers=["/publisher"], msg_size_bytes=None)],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        nodes = data["ros2 nodes info"]
        t1 = list(nodes.values())[0]["published topics"]["topic 1"]
        assert "avg msg size bytes" not in t1

    def test_node_with_no_matching_topics_has_no_topic_keys(self):
        """A node not mentioned in any topic connection has no published/subscribed keys."""
        topo = PipelineTopology(
            nodes=["/publisher", "/idle_node"],
            topics=[_make_topic(publishers=["/publisher"], subscribers=[])],
        )
        data = _parse_json(_format_pipeline_topology_section(topo))
        nodes = data["ros2 nodes info"]
        idle = next(v for v in nodes.values() if v["node name"] == "/idle_node")
        assert "published topics" not in idle
        assert "subscribed topics" not in idle
