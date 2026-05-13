"""Asynchronous Claude CLI subprocess runner."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from .models import StageMetrics


def parse_claude_json(log_text: str) -> tuple[str, Optional[dict]]:
    """Parse Claude CLI ``--output-format json`` output.

    Reads the ``result`` field (top-level) and ``usage`` sub-object,
    fixing the common shell-script bug where it looked at ``content`` instead.
    """
    for line in reversed(log_text.strip().split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                result_text = data.get("result", "")
                usage = data.get("usage", {})
                return result_text, {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }
            except json.JSONDecodeError:
                continue

    return log_text.strip(), None


async def run_claude(
    prompt: str,
    log_path: Path,
    *,
    timeout: int = 600,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    output_format: str = "json",
    cwd: Path | None = None,
) -> tuple[str, StageMetrics]:
    """Execute a Claude agent via the CLI, capturing its result.

    Args:
        prompt: The full prompt text.
        log_path: Where to dump the raw CLI output for debugging.
        timeout: Seconds before the agent is killed.
        model: Claude model override (e.g. ``"opus"``).
        allowed_tools: Tools the agent is permitted to use.
        output_format: ``--output-format`` value.
        cwd: Working directory for the subprocess.

    Returns:
        ``(result_text, metrics)`` — the extracted result and usage stats.
    """
    log_path = Path(log_path)
    if log_path.exists():
        log_path.unlink()

    cmd = ["claude", "-p", prompt, "--output-format", output_format]

    if model:
        cmd.extend(["--model", model])

    if allowed_tools:
        cmd.append("--allowed-tools")
        cmd.append(" ".join(allowed_tools))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd) if cwd else None,
    )

    metrics = StageMetrics()

    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        metrics.timed_out = True
        log_path.write_text("[TIMEOUT]")
        os.chmod(log_path, 0o600)
        return "[TIMEOUT]", metrics

    text = stdout_b.decode("utf-8", errors="replace")
    log_path.write_text(text)
    os.chmod(log_path, 0o600)

    result_text, usage = parse_claude_json(text)
    if usage:
        metrics.input_tokens = usage["input_tokens"]
        metrics.output_tokens = usage["output_tokens"]

    return result_text, metrics
