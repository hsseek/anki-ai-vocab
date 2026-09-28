"""The journal summary reports comparable model latency."""

import subprocess
import sys
from pathlib import Path


def test_metric_summary_ignores_other_logs_and_reports_percentiles():
    script = Path(__file__).parents[1] / "scripts" / "summarize_metrics.py"
    logs = """\
ordinary server log
{"metric":"attempt_completed","request_id":"a","model":"fast","first_chunk_ms":10,"generation_first_meaning_ms":50,"generation_total_ms":100}
prefix {"metric":"attempt_completed","request_id":"b","model":"fast","first_chunk_ms":20,"generation_first_meaning_ms":70,"generation_total_ms":200}
{"metric":"client_first_meaning","request_id":"a","elapsed_ms":60}
{"metric":"client_complete","request_id":"a","elapsed_ms":120}
{"metric":"attempt_invalid","request_id":"c","model":"fast"}
{"metric":"model_unavailable","request_id":"d","model":"slow"}
"""
    result = subprocess.run(
        [sys.executable, str(script)], input=logs, text=True,
        capture_output=True, check=True,
    )
    assert "fast\t2\t15/20 ms\t60/70 ms\t150/200 ms\t60/60 ms\t120/120 ms\t1\t0" in result.stdout
    assert "slow\t0\t-\t-\t-\t-\t-\t0\t1" in result.stdout
