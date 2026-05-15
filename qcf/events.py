"""Unified event log — /tmp/qcf-events.jsonl.

Replaces the legacy /tmp/qcf-status.json and AgentProgress JSON overwrite
with a single append-only JSONL stream that all pipeline stages write to.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class EventLogger:
    """Append-only JSONL event log.

    Schema per line (all fields are optional except ``ts`` and ``event``):

    .. code-block:: json

        {"ts":"...","event":"stage.start","stage":"implement","round":1}
        {"ts":"...","event":"stage.end","stage":"implement","result":"PASS","tokens_in":5000}
        {"ts":"...","event":"timeout","stage":"implement","round":1}
        {"ts":"...","event":"verdict","stage":"review","result":"FAIL"}
        {"ts":"...","event":"artifact.validation","result":"FAIL","details":"..."}
        {"ts":"...","event":"replan","reason":"max_consecutive_fails"}
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event_type: str, **data: Any) -> None:
        """Append one event as a JSONL line."""
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "event": event_type,
        }
        record.update(data)
        try:
            with open(self.path, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        """Return last *n* events by reading the file tail."""
        if not self.path.exists():
            return []
        try:
            result = subprocess.run(
                ["tail", "-n", str(n), str(self.path)],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            return [json.loads(l) for l in lines]
        except Exception:
            return []

    def follow(self, n: int = 10) -> list[dict[str, Any]]:
        """Return last *n* events wrapped for ``qcf status --watch`` display."""
        return self.tail(n)
