# Example: Publisher/Subscriber Pipeline

A simple inter-process pub/sub pipeline used to demonstrate the ROS2 DDSConfig Optimizer.

The publisher sends `std_msgs/msg/Header` messages on `/counter` at 10 Hz; the subscriberreceives them.

End-to-end latency is measured from the publisher's `header.stamp` to receipt at the subscriber side.

## Pipeline

```
publisher_node  ──/counter (std_msgs/msg/Header @ 10 Hz)──►  subscriber_node
                                    │
                                    └──►  MonitorNode (benchmark only)
```

- **publisher**: publishes `frame_id` = incrementing counter string, `stamp` = publish time
- **subscriber**: subscribes to `/counter` and logs each received value

## Run

```bash
# Step 0: setup
git clone https://github.com/qualcomm-qrb-ros/ROS2-DDSConfig-Optimizer
export OPTIMIZER_ROOT=/path/to/ROS2-DDSConfig-Optimizer
cd $OPTIMIZER_ROOT
uv sync
source .venv/bin/activate

# Step 1: build example ros2 application
cd $OPTIMIZER_ROOT/example/src
git clone https://github.com/qualcomm-qrb-ros/ros2_benchmark

source /opt/ros/<distro>/setup.bash   # humble or jazzy
cd $OPTIMIZER_ROOT/example && colcon build
source install/setup.bash

# Step 2: run the optimizer
cd $OPTIMIZER_ROOT
export LLM_API_KEY=<your-api-key>

uv run dds-optimizer run \
    --requirements example/user_requirements.xml \
    --initial-config example/fast-dds-latency-param.xml
```

## Understanding the Results

Results are saved under `data/optimization_history/<YYYYMMDD_HHMMSS>/`:

```
data/optimization_history/20260309_113230/
├── epoch_1/
│   ├── fastdds_config.xml       ← FastDDS config used in this epoch
│   |── benchmark_result.json    ← raw benchmark metrics for this epoch
│   └── llm_conversation.md      ← conversation content between user and LLM
├── epoch_2/
│   ├── fastdds_config.xml
│   |── benchmark_result.json
│   └── llm_conversation.md
├── best_config.xml              ← best config found across all epochs
└── session_summary.json         ← scores and metrics for every epoch
```

**Quick inspection commands:**

```bash
# Scores and metrics for every epoch
cat data/optimization_history/$(ls -t data/optimization_history/ | head -1)/session_summary.json

# Raw benchmark output for a specific epoch
cat data/optimization_history/$(ls -t data/optimization_history/ | head -1)/epoch_1/benchmark_result.json

# Apply the best config to your own application
export FASTRTPS_DEFAULT_PROFILES_FILE=$(ls -t data/optimization_history/*/best_config.xml | head -1)
ros2 launch pipeline_launch pubsub.launch.py
```

### Reading `session_summary.json`

Each entry in `iterations` is one optimization epoch:

```json
{
  "session_id": "ceef39aa",
  "success": true,
  "iterations": [
    {
      "iteration_number": 1,
      "performance_score": 0.72,
      "required_metrics_met": false,
      "optional_metrics_met": false,
      "llm_reasoning": "Targeting sub-10ms latency with RELIABLE QoS...",
      "benchmark_error": null,
      "results": {
        "mean_latency_ms": 18.5,
        "msgs_per_sec": 9.8,
        "packet_loss_rate": 0.0
      }
    },
    {
      "iteration_number": 2,
      "performance_score": 0.98,
      "required_metrics_met": true,
      "optional_metrics_met": true,
      "llm_reasoning": "Reduced history depth and switched to SHM transport...",
      "benchmark_error": null,
      "results": {
        "mean_latency_ms": 4.2,
        "msgs_per_sec": 10.0,
        "packet_loss_rate": 0.0
      }
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `performance_score` | 0.0–1.0 composite score; 1.0 means all targets hit |
| `required_metrics_met` | `true` when all hard requirements (latency, reliability) are satisfied |
| `optional_metrics_met` | `true` when all soft requirements (throughput, CPU, memory) are satisfied |
| `results.mean_latency_ms` | Measured mean end-to-end latency in milliseconds |
| `llm_reasoning` | The LLM's explanation for the parameter choices it made this epoch |
| `benchmark_error` | Non-null if the benchmark failed to run; optimizer retries up to 3 times |

The full FastDDS parameter set for each epoch is in `epoch_N/fastdds_config.xml` — not repeated in `session_summary.json`.