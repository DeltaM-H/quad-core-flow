"""Pipeline hook system — shell-command hooks à la git hooks.

Usage
-----
Place executable scripts in ``.qcf-hooks/<event-name>/``
(e.g. ``.qcf-hooks/on-passed/slack-notify.sh``).

Scripts receive context via environment variables (``QCF_*``)
and are executed in sorted order.

Hooks can also be configured inline in ``qcf.toml`` under ``[hooks]``.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


# ── Event names ──────────────────────────────────────────────
# Pipeline lifecycle
EVT_PRE_START = "pre-start"
EVT_POST_START = "post-start"
# Per stage
EVT_PRE_STAGE = "pre-stage"
EVT_POST_STAGE = "post-stage"
# Per round
EVT_PRE_ROUND = "pre-round"
EVT_POST_ROUND = "post-round"
# Decisions
EVT_ON_PASSED = "on-passed"
EVT_ON_FAILED = "on-failed"
EVT_ON_EXHAUSTED = "on-exhausted"
EVT_ON_ERROR = "on-error"

# Allowlist of valid event names for MEDIUM-3 security hardening
_VALID_EVENTS: frozenset[str] = frozenset({
    EVT_PRE_START, EVT_POST_START,
    EVT_PRE_STAGE, EVT_POST_STAGE,
    EVT_PRE_ROUND, EVT_POST_ROUND,
    EVT_ON_PASSED, EVT_ON_FAILED, EVT_ON_EXHAUSTED, EVT_ON_ERROR,
})


def _env_context(**ctx: Any) -> dict[str, str]:
    """Build environment dict with QCF_* vars from context."""
    env = os.environ.copy()
    env["QCF_EVENT"] = ctx.get("event", "")
    for k, v in ctx.items():
        key = f"QCF_{k.upper()}"
        if isinstance(v, bool):
            env[key] = "1" if v else "0"
        elif v is not None:
            env[key] = str(v)
    return env


class Hooks:
    """Pipeline hook runner.

    Two sources of hooks (both optional):
      1. **Script directory** — ``.qcf-hooks/<event>/`` executable files
      2. **Inline commands** — shell command strings registered via ``add_command()``
      3. **Python callables** — registered via ``register()``

    Hooks execute **in order**: scripts first (sorted), then inline commands,
    then Python callbacks. If any hook returns a non-zero exit code
    (or raises), the sequence stops and the outcome is returned.
    """

    def __init__(self, hooks_dir: Path | None = None) -> None:
        self._hooks_dir = hooks_dir  # .qcf-hooks
        self._inline: dict[str, list[str]] = {}   # event → [cmd, ...]
        self._callbacks: dict[str, list[Callable[..., Any]]] = {}

    # ── Registration ──────────────────────────────────────────

    def add_command(self, event: str, command: str) -> None:
        """Register a shell command for *event*."""
        if event not in _VALID_EVENTS:
            raise ValueError(
                f"Invalid hook event: {event!r}. "
                f"Valid events: {sorted(_VALID_EVENTS)}"
            )
        self._inline.setdefault(event, []).append(command)

    def add_commands(self, config: dict[str, list[str]]) -> None:
        """Bulk-register from a ``{event: [cmd, ...]}`` dict."""
        for event, cmds in config.items():
            if event not in _VALID_EVENTS:
                raise ValueError(
                    f"Invalid hook event: {event!r}. "
                    f"Valid events: {sorted(_VALID_EVENTS)}"
                )
            for cmd in cmds:
                self.add_command(event, cmd)

    def register(self, event: str, fn: Callable[..., Any]) -> None:
        """Register a Python callable for *event*."""
        if event not in _VALID_EVENTS:
            raise ValueError(
                f"Invalid hook event: {event!r}. "
                f"Valid events: {sorted(_VALID_EVENTS)}"
            )
        self._callbacks.setdefault(event, []).append(fn)

    # ── Execution ────────────────────────────────────────────

    def run(self, event: str, **ctx: Any) -> int:
        """Run all hooks for *event*. Returns 0 if all OK, else the first non-zero exit code."""
        ctx.setdefault("event", event)
        env = _env_context(**ctx)
        exit_code = 0

        # 1. Script hooks (.qcf-hooks/<event>/*)
        if self._hooks_dir:
            script_dir = self._hooks_dir / event
            if script_dir.is_dir():
                for script in sorted(script_dir.iterdir()):
                    if script.is_file() and os.access(script, os.X_OK):
                        ret = subprocess.run(
                            [str(script)], env=env,
                            capture_output=False,
                        ).returncode
                        if ret != 0:
                            exit_code = ret
                            break

        # 2. Inline commands
        for cmd in self._inline.get(event, []):
            ret = subprocess.run(
                cmd, env=env, shell=True, capture_output=False,
            ).returncode
            if ret != 0:
                exit_code = ret
                break

        # 3. Python callbacks
        for fn in self._callbacks.get(event, []):
            try:
                fn(**ctx)
            except Exception as e:
                print(f"  [hook error] {event} handler {fn.__name__}: {e}", file=sys.stderr)
                exit_code = 1
                break

        return exit_code

    async def run_async(self, event: str, **ctx: Any) -> int:
        """Async variant — runs in a thread executor to avoid blocking the event loop."""
        return await asyncio.to_thread(self.run, event, **ctx)

    # ── Discovery ────────────────────────────────────────────

    @classmethod
    def discover(cls, base_dir: Path | None = None) -> Hooks:
        """Discover hooks from ``.qcf-hooks/`` directory."""
        hooks_dir = None
        if base_dir:
            candidate = base_dir / ".qcf-hooks"
            if candidate.is_dir():
                hooks_dir = candidate
        return cls(hooks_dir=hooks_dir)

    @property
    def registered_events(self) -> list[str]:
        """List all events that have at least one hook configured."""
        events: set[str] = set()
        events.update(self._inline.keys())
        events.update(self._callbacks.keys())
        if self._hooks_dir and self._hooks_dir.is_dir():
            for d in self._hooks_dir.iterdir():
                if d.is_dir() and any(f.is_file() and os.access(f, os.X_OK) for f in d.iterdir()):
                    events.add(d.name)
        return sorted(events)
