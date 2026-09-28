"""Privacy-safe structured performance logs.

Each metric is one compact JSON object, which makes the systemd journal useful
both to a person and to the summary script. Callers must pass only timings,
counts, provider/model names, and generated request IDs--never vocabulary text.
"""

import json
import logging
from typing import Any


# Uvicorn owns this logger hierarchy and sends INFO records to stderr, which
# systemd captures. The child name also remains easy to select in tests.
log = logging.getLogger("uvicorn.error.kanki.metrics")


def emit_metric(event: str, request_id: str, **fields: Any) -> None:
    """Write one JSON metric without user or generated text."""
    payload = {"metric": event, "request_id": request_id, **fields}
    log.info(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


def elapsed_ms(start: float, end: float) -> int:
    """Return a monotonic duration rounded to whole milliseconds."""
    return max(0, round((end - start) * 1000))
