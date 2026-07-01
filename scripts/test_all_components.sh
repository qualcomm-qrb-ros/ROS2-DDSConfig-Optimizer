#!/usr/bin/env bash
# Copyright (c) 2026 Qualcomm Innovation Center, Inc. All rights reserved.
# SPDX-License-Identifier: BSD-3-Clause-Clear
#
# Run all unit tests and component checks.
# Usage: ./scripts/test_all_components.sh [--verbose]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERBOSE="${1:-}"

cd "$PROJECT_DIR"

echo "============================================================"
echo "ROS2 DDSConfig Optimizer - Component Tests"
echo "============================================================"
echo ""

# Check Python environment
echo "[1/6] Checking Python environment..."
uv run python --version
uv run python -c "import dds_optimizer; print('  Package import: OK')"
echo ""

# Run unit tests
echo "[2/6] Running unit tests..."
if [ "$VERBOSE" = "--verbose" ] || [ "$VERBOSE" = "-v" ]; then
    uv run pytest tests/unit/ -v --tb=short
else
    uv run pytest tests/unit/ --tb=short -q
fi
echo ""

# Test requirements parser
echo "[3/6] Testing requirements parser..."
uv run python -c "
from dds_optimizer.requirements.parser import parse_requirements
import tempfile, os

xml = '''<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<optimization_requirements>
    <benchmark><test_file>/tmp/bench.py</test_file><launch_command>launch_test</launch_command></benchmark>
    <performance_requirements>
        <latency optional=\"false\"><target_mean_ms>10</target_mean_ms></latency>
    </performance_requirements>
    <optimization_settings><max_iterations>3</max_iterations><convergence_threshold>0.05</convergence_threshold></optimization_settings>
    <llm_config><provider>openai</provider><model>gpt-4</model><base_url>https://api.openai.com/v1</base_url><api_key_env>OPENAI_API_KEY</api_key_env></llm_config>
</optimization_requirements>'''

with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
    f.write(xml)
    tmp = f.name

try:
    config = parse_requirements(tmp)
    assert config.benchmark.test_file == '/tmp/bench.py'
    assert config.performance_requirements.latency.target_mean_ms == 10.0
    print('  Requirements parser: OK')
finally:
    os.unlink(tmp)
"
echo ""

# Test config generator
echo "[4/6] Testing config generator..."
uv run python -c "
import tempfile
from pathlib import Path
from dds_optimizer.config.generator import generate_fastdds_config
from dds_optimizer.config.validator import validate_config
from dds_optimizer.models import DDSParameterSet

params = DDSParameterSet(
    parameters={
        'history_depth': 10,
        'reliability_kind': 'RELIABLE',
        'intraprocess_delivery': 'FULL',
    },
    reasoning='Test'
)

with tempfile.TemporaryDirectory() as tmpdir:
    output = Path(tmpdir) / 'test.xml'
    generate_fastdds_config(params, output)
    warnings = validate_config(output)
    print(f'  Config generator: OK (warnings: {len(warnings)})')
    content = output.read_text()
    assert '<?xml version' in content
    print('  Config validator: OK')
"
echo ""

# Test benchmark results parser
echo "[5/6] Testing benchmark results parser..."
uv run python -c "
import json, tempfile
from pathlib import Path
from dds_optimizer.benchmark.results_parser import parse_benchmark_results

result = {
    'BasicPerformanceMetrics.MEAN_LATENCY': 9.85,
    'BasicPerformanceMetrics.MEAN_FRAME_RATE': 104.84,
    'BasicPerformanceMetrics.NUM_MISSED_FRAMES': 0.0,
    'BasicPerformanceMetrics.NUM_FRAMES_SENT': 557.0,
    'ResourceMetrics.MEAN_OVERALL_CPU_UTILIZATION': 2.56,
}

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(result, f)
    tmp = f.name

import os
try:
    results = parse_benchmark_results(Path(tmp))
    assert abs(results.mean_latency_ms - 9.85) < 0.01
    assert results.packet_loss_rate == 0.0
    print(f'  Results parser: OK (latency={results.mean_latency_ms:.2f}ms, loss={results.packet_loss_rate:.4f})')
finally:
    os.unlink(tmp)
"
echo ""

# Test LLM response parser
echo "[6/6] Testing LLM response parser..."
uv run python -c "
from dds_optimizer.llm.response_parser import parse_llm_response

response = '''
\`\`\`json
{
    \"set\": {
        \"history_depth\": 10,
        \"reliability_kind\": \"RELIABLE\",
        \"intraprocess_delivery\": \"FULL\"
    },
    \"delete\": []
}
\`\`\`
'''

param_set = parse_llm_response(response)
assert param_set.parameters['history_depth'] == 10
assert param_set.parameters['reliability_kind'] == 'RELIABLE'
print(f'  LLM response parser: OK ({len(param_set.parameters)} parameters)')
"
echo ""

echo "============================================================"
echo "All component tests PASSED!"
echo "============================================================"
