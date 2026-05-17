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

    Extracts cumulative usage across ALL API turns in the conversation
    (not just the final one), plus prompt-caching metadata. Each tool-use
    round-trip generates a separate API call; summing them gives the true
    billed input.
    """
    lines = log_text.strip().split("\n")

    total_input = 0
    total_output = 0
    tool_calls = 0
    cache_creation = 0
    cache_read = 0
    result_text = ""
    found_usage = False

    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
            # result belongs to the last JSON blob
            if "result" in data and not result_text:
                result_text = data.get("result", "")

            usage = data.get("usage")
            if usage:
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)
                cache_creation += usage.get("cache_creation_input_tokens", 0)
                cache_read += usage.get("cache_read_input_tokens", 0)
                tool_calls += 1
                found_usage = True
        except json.JSONDecodeError:
            continue

    if not found_usage:
        return result_text or log_text.strip(), None

    return result_text or log_text.strip(), {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "tool_calls": tool_calls,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
    }


async def run_claude(
    prompt: str,
    log_path: Path,
    *,
    timeout: int = 600,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    output_format: str = "json",
    thinking_budget: int | None = None,
    permission_mode: str | None = None,
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
        permission_mode: Permission mode override (e.g. ``"acceptEdits"`` to auto-accept
            file edit/write prompts in automated pipeline contexts).
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

    if thinking_budget:
        cmd.extend(["--thinking-budget", str(thinking_budget)])

    if allowed_tools:
        cmd.append("--allowed-tools")
        cmd.append(" ".join(allowed_tools))

    if permission_mode:
        cmd.extend(["--permission-mode", permission_mode])

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
        metrics.tool_calls = usage["tool_calls"]
        metrics.cache_creation_input_tokens = usage["cache_creation_input_tokens"]
        metrics.cache_read_input_tokens = usage["cache_read_input_tokens"]

    return result_text, metrics
