"""AGENT_PROGRESS.jsonl — append-only pipeline dashboard.

Replaces the legacy JSON-overwrite with a JSONL append stream.
Each line is a self-contained event.  Use ``tail -f | jq`` for live
monitoring or call ``.snapshot()`` for ``qcf status`` display.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

AGENT_PROGRESS_PATH = Path("/tmp/AGENT_PROGRESS.jsonl")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AgentProgress:
    """Append-only JSONL pipeline dashboard.

    Unlike the legacy JSON-overwrite version, each ``update_*`` call
    appends one JSON line.  No history cap, no tasks_done accumulation,
    no next_action state — consumers read the tail.
    """

    def __init__(self, target: str = "", max_rounds: int = 3) -> None:
        self._append({
            "event": "init",
            "target": target,
            "max_rounds": max_rounds,
        })

    def update_before_round(self, stage: str, round_num: int, **kwargs: Any) -> None:
        """Append a stage-start event."""
        record: dict[str, Any] = {
            "event": "stage_start",
            "stage": stage,
            "round": round_num,
        }
        record.update({k: v for k, v in kwargs.items() if v})
        self._append(record)

    def update_on_complete(self, result: dict[str, Any]) -> None:
        """Append a stage-end event."""
        record: dict[str, Any] = {
            "event": "stage_end",
        }
        record.update(result)
        self._append(record)

    def _append(self, record: dict[str, Any]) -> None:
        """Append one JSON line to the JSONL file."""
        record["_updated_at"] = _now_iso()
        try:
            AGENT_PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AGENT_PROGRESS_PATH, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            os.chmod(AGENT_PROGRESS_PATH, 0o600)
        except OSError:
            pass

    def snapshot(self, n: int = 20) -> list[dict[str, Any]]:
        """Return last *n* events via ``tail``."""
        if not AGENT_PROGRESS_PATH.exists():
            return []
        try:
            result = subprocess.run(
                ["tail", "-n", str(n), str(AGENT_PROGRESS_PATH)],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
            return [json.loads(l) for l in lines]
        except Exception:
            return []
