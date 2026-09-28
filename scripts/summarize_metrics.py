#!/usr/bin/env python3
"""Summarize Kanki JSON timing logs read from stdin."""

import json
import statistics
import sys
from collections import defaultdict


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


rows = defaultdict(lambda: defaultdict(list))
counts = defaultdict(lambda: defaultdict(int))
items = []
request_models = {}

for line in sys.stdin:
    try:
        item = json.loads(line[line.index("{"):])
    except (ValueError, json.JSONDecodeError):
        continue
    event = item.get("metric")
    model = item.get("model")
    if not event:
        continue
    items.append(item)
    if event == "attempt_completed" and model:
        request_models[item.get("request_id")] = model
    if not model:
        continue
    counts[model][event] += 1
    if event == "attempt_completed":
        for field in (
            "first_chunk_ms", "generation_first_meaning_ms", "generation_total_ms"
        ):
            value = item.get(field)
            if isinstance(value, int):
                rows[model][field].append(value)

for item in items:
    event = item.get("metric")
    if event not in ("client_first_meaning", "client_complete"):
        continue
    model = request_models.get(item.get("request_id"))
    value = item.get("elapsed_ms")
    if model and isinstance(value, int):
        rows[model][event + "_ms"].append(value)

if not rows and not counts:
    raise SystemExit("No Kanki metric records found on stdin.")

print("model\truns\tprovider chunk p50/p95\tserver meaning p50/p95\tserver total p50/p95\tbrowser meaning p50/p95\tbrowser total p50/p95\tinvalid\tunavailable")
for model in sorted(set(rows) | set(counts)):
    def summary(field: str) -> str:
        values = rows[model][field]
        if not values:
            return "-"
        return f"{round(statistics.median(values))}/{percentile(values, .95)} ms"

    print("\t".join([
        model,
        str(counts[model]["attempt_completed"]),
        summary("first_chunk_ms"),
        summary("generation_first_meaning_ms"),
        summary("generation_total_ms"),
        summary("client_first_meaning_ms"),
        summary("client_complete_ms"),
        str(counts[model]["attempt_invalid"]),
        str(counts[model]["model_unavailable"]),
    ]))
