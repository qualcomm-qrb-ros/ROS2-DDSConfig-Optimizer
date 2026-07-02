# Talker / Listener Testing Pipeline

A minimal, build-free ROS2 pipeline used to exercise the DDS optimizer end to
end, plus a `ros2_benchmark` launch-test script that measures it.

## Components

| File | Role |
|---|---|
| `talker.py` | rclpy node. Publishes `std_msgs/msg/Header` on `/chatter` at 10 Hz. `header.stamp` = publish time (for E2E latency), `header.frame_id` = incrementing counter. |
| `listener.py` | rclpy node. Subscribes to `/chatter` and logs receipt counts. |
| `chatter_benchmark.py` | `ros2_benchmark` LIVE-mode benchmark. Starts talker + listener and a `ros2_benchmark::MonitorNode` on `/chatter` to measure end-to-end latency and throughput. |

Both nodes are pure `rclpy`, so **no colcon build is required** — they run
directly with `python3`.

## Running the benchmark

```bash
source /opt/ros/jazzy/setup.bash

# FastDDS (default RMW)
launch_test example/pipeline/chatter_benchmark.py

# CycloneDDS
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
launch_test example/pipeline/chatter_benchmark.py
```

The benchmark runs in LIVE mode: the pipeline nodes generate their own data
(no rosbag needed). It runs `test_iterations` iterations of `benchmark_duration`
seconds each and reports mean end-to-end latency, throughput, and CPU usage.

## Result output

By default the result JSON is written to `/tmp/r2b-log-<timestamp>.json`.
Override the location with the environment variables `ros2_benchmark` reads:

```bash
export ROS2_BENCHMARK_OVERRIDE_LOG_FOLDER=/path/to/out
export ROS2_BENCHMARK_OVERRIDE_LOG_FILE_NAME=benchmark_result
```

These are the same variables the optimizer's benchmark launcher sets per epoch.

## Running the two nodes on their own (without benchmarking)

```bash
source /opt/ros/jazzy/setup.bash
python3 example/pipeline/talker.py      # terminal 1
python3 example/pipeline/listener.py    # terminal 2
```
