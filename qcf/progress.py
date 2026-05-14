"""AGENT_PROGRESS.json — structured pipeline dashboard.

Writes an append-only history of actions taken during the QCF pipeline,
separate from the low-level /tmp/qcf-status.json operational log.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

AGENT_PROGRESS_PATH = Path("/tmp/AGENT_PROGRESS.json")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_agent_progress() -> dict[str, Any]:
    if AGENT_PROGRESS_PATH.exists():
        try:
            return json.loads(AGENT_PROGRESS_PATH.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    return {}


class AgentProgress:
    """Writes a structured dashboard to ``/tmp/AGENT_PROGRESS.json``.

    Schema:
        target (str): Current pipeline target description.
        tasks_done (list[str]): Completed tasks in order.
        next_action (str): What will happen next.
        current_stage (str): Current pipeline stage.
        round (int): Current round number.
        max_rounds (int): Maximum configured rounds.
        action_suggestion (str): RETRY | REPLAN.
        failed_stages (list[str]): Stages that have failed.
        updated_at (str): ISO-8601 timestamp.
        history (list[dict]): Append-only event log.
    """

    def __init__(self, target: str = "", max_rounds: int = 3) -> None:
        # Preserve existing data if restarting
        existing = _read_agent_progress()
        self.data: dict[str, Any] = {
            "target": target or existing.get("target", ""),
            "tasks_done": existing.get("tasks_done", []),
            "next_action": "Starting pipeline",
            "current_stage": "initializing",
            "round": 0,
            "max_rounds": max_rounds,
            "action_suggestion": "RETRY",
            "failed_stages": [],
            "updated_at": _now_iso(),
            "history": existing.get("history", []),
        }
        self._write()

    def update_before_round(self, stage: str, round_num: int, target: str = "") -> None:
        """Called by engine before each stage starts."""
        self.data["current_stage"] = stage
        self.data["round"] = round_num
        self.data["next_action"] = f"Running {stage} for round {round_num}"
        if target:
            self.data["target"] = target
        self.data["updated_at"] = _now_iso()
        self._write()

    def update_on_complete(self, result: dict[str, Any]) -> None:
        """Called when a round or stage finishes."""
        task_label = result.get("task") or result.get("stage", "")
        if task_label:
            self.data["tasks_done"].append(task_label)

        if result.get("stage"):
            status = result.get("status", "done")
            self.data["current_stage"] = f"{result['stage']} ({status})"

        if result.get("action_suggestion"):
            self.data["action_suggestion"] = result["action_suggestion"]

        if result.get("failed_stages"):
            self.data["failed_stages"] = list(set(self.data["failed_stages"] + result["failed_stages"]))

        if result.get("next_action"):
            self.data["next_action"] = result["next_action"]

        self.data["history"].append({
            "stage": result.get("stage", ""),
            "round": result.get("round", 0),
            "result": result.get("status", ""),
            "timestamp": _now_iso(),
        })
        # Cap history to last 50 entries
        if len(self.data["history"]) > 50:
            self.data["history"] = self.data["history"][-50:]

        self.data["updated_at"] = _now_iso()
        self._write()

    def _write(self) -> None:
        """Atomic write via temp file + rename to avoid partial reads."""
        tmp = AGENT_PROGRESS_PATH.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2, default=str)
            )
            os.chmod(tmp, 0o600)
            tmp.rename(AGENT_PROGRESS_PATH)
        except OSError:
            pass  # Best-effort write
