<div align="center">

# ROS2 DDSConfig Optimizer

[![ROS](https://img.shields.io/badge/ROS-Humble%20%7C%20Jazzy-green)](https://www.ros.org/)
[![DDS](https://img.shields.io/badge/DDS-FastDDS_2.14.5%20%7C%20CycloneDDS_0.10.5-orange)](https://fast-dds.docs.eprosima.com/)
[![License](https://img.shields.io/badge/License-BSD--3--Clause-blue)](#license)

<p>
  <strong>An AI-driven tool that automatically tunes DDS configuration for ROS2 applications.</strong>
</p>

<p>
  <img src="./data/images/background.png" width="70%" alt="ROS2 DDSConfig Optimizer">
</p>

<p>
  <a href="#overview">Overview</a> •
  <a href="#improvement-showcase">Improvement Showcase</a> •
  <a href="#requirements">Requirements</a> •
  <a href="#usage">Usage</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#license">License</a>
</p>

</div>

---

## Overview

**😡Are you still struggling to tune hundreds of DDS parameters?**

ROS2 DDSConfig Optimizer is here to help! It uses LLMs to automatically tune DDS configuration for ROS 2 applications.

🫵You only need to provide:

1. **Performance targets** such as latency, throughput, reliability, CPU usage, and memory usage in a simple XML file
2. **An initial DDS configuration** as the baseline

🏃‍♀️‍➡️ROS2 DDSConfig Optimizer will then automatically:

1. Run your ROS 2 application
2. Benchmark your ROS 2 application
3. Tune DDS parameters iteratively

😆Finially, you will get an optimized DDS configuration tailored to your ROS 2 application.

---

## Improvement Showcase

We simulated a multi-sensor graph running on a Qualcomm device, comprising **10 nodes** and **27 topics** — the kind that is painful to tune by hand:

<p>
  <img src="./data/images/improvement-result-pipeline.png" width="100%" alt="improvement-result-pipeline">
</p>

**Why this is hard to tune manually:**

- **140+** DDS configurable parameters — it is unclear which ones even need tuning.
- **27** topics and **9** message types of different sizes — tuning them by hand takes a huge amount of time.

However, don’t worry — we can use ROS2-DDSConfig-Optimizer for tuning. We use the **anthropic/claude-sonnet-4.6** model, set **max_iterations to 5**, and then start optimizing only for **latency** and **packet loss**.

Let's see the performance comparison:

| Metric            | Baseline (default config) | After optimization | Change     |
| ----------------- | ------------------------- | ------------------ | ---------- |
| Mean E2E latency  | 122.6 ms                  | **86.3 ms**        | **−29.6%** |
| p95 / p99 latency | 228.0 ms                  | **159.5 ms**       | **−30.0%** |
| Packet loss       | 7.5 %                     | **0.4 %**          | −7.1 pts   |

As the numbers show, ROS2-DDSConfig-Optimizer delivers a substantial, real performance gain — cutting mean end-to-end latency by nearly 30% and bringing packet loss under the 1% target, all **without a single manual edit** to the DDS configuration.

The table below compares manual tuning with ROS2-DDSConfig-Optimizer across several dimensions:

| Dimension | Manual tuning | ROS2-DDSConfig-Optimizer |
|---|---|---|
| Human involvement | Expert trial-and-error throughout | One command, zero intervention |
| Time cost | Hours to days | Minutes (5 rounds, fully automated) |
| DDS / networking expertise | Required, and deep | Not required |
| Parameter-space coverage | A few parameters by intuition | Systematically explores 40+ per round |
| Reproducibility | Person-dependent, hard to reproduce | Every config + reasoning logged |


## Requirements

| Item | Requirement |
|---|---|
| **OS** | Ubuntu |
| **ROS 2** | Humble, Jazzy |
| **Package manager** | [uv](https://docs.astral.sh/uv/) ≥ 0.7.8 |

---

## Usage

See **[`example/README.md`](example/README.md)** for a complete, copy-paste-ready walkthrough.

### Step 1: Setup

```bash README.md
cd ROS2-DDSConfig-Optimizer
uv sync
```

### Step 2: Provide Performance Targets and Initial DDS Configuration

See:

- [`user_requirements_template.xml`](data/templates/user_requirements_template.xml)
- [`fastdds_config_template.xml`](data/templates/fastdds_config_template.xml)

CycloneDDS is now supported alongside FastDDS. To optimize a CycloneDDS deployment, set `<dds_implementation>cyclonedds</dds_implementation>` in your `user_requirements.xml` (the default is `fastdds`).

### Step 3: Choose a Benchmark Tool and Provide Benchmark Scripts

Currently, only [`ros2_benchmark`](https://github.com/qualcomm-qrb-ros/ros2_benchmark) is supported.

### Step 4: Run the Optimizer

```bash README.md
uv run dds-optimizer run \
    --requirements /path/to/user_requirements.xml \
    --initial-config /path/to/initial_DDS_config.xml
```

### Step 5: View Optimization History and Get BEST config

> the best config will be placed in data/optimization_history

```bash README.md
uv run dds-optimizer dashboard --port 5000
```

Open `http://localhost:5000/` in your browser:

<p align="center">
  <img src="./data/images/dashboard.png" width="85%" alt="ROS2 DDSConfig Optimizer Dashboard">
</p>

---

## Contributing

We welcome community contributions.

To get started, please read [CONTRIBUTING.md](CONTRIBUTING.md).
Feel free to open an issue for bug reports, feature requests, or general discussion.

---

## License

This project is licensed under the [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) License. See [LICENSE](./LICENSE) for the full license text.
