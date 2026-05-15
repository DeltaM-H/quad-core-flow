"""Watch mode — listens for new design documents and triggers QCF."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from .config import Config
from .engine import QCFEngine, _emit_event


async def watch_mode(config: Config) -> None:
    """Monitor ``config.tech_lead_dir`` for new ``.md`` files.

    Uses ``inotifywait`` when available (Linux, low CPU); falls back to
    file-polling (cross-platform).
    """
    watch_dir = config.tech_lead_dir
    if not watch_dir.exists():
        print(f"Error: watch directory not found: {watch_dir}")
        print("Create it or adjust paths in qcf.toml.")
        return

    print(f" Watching: {watch_dir}")
    print(" Waiting for new design documents...\n")

    _emit_event(config, "watch.start",
                 watch_dir=str(watch_dir),
                 started_at=time.strftime("%Y-%m-%d %H:%M:%S"))

    # Pre-populate known files so we don't re-process existing ones
    known: set[str] = set()
    for f in watch_dir.iterdir():
        if f.suffix == ".md" and not f.name.endswith(".tmp.md"):
            known.add(f.name)

    # Determine watcher strategy
    if shutil.which("inotifywait"):
        await _watch_inotify(config, watch_dir, known)
    else:
        print("  [inotifywait not found — falling back to polling (every 5s)]")
        await _watch_poll(config, watch_dir, known)


async def _watch_inotify(config: Config, watch_dir: Path, known: set[str]) -> None:
    """Low-overhead inotify-based watch (Linux only)."""
    proc = await asyncio.create_subprocess_exec(
        "inotifywait", "-m", "-e", "create,moved_to",
        "--format", "%f",
        str(watch_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        filename = line.decode().strip()

        if not filename.endswith(".md") or filename.endswith(".tmp.md"):
            continue
        if filename in known:
            continue
        known.add(filename)

        await _handle_new_doc(config, watch_dir / filename)


async def _watch_poll(config: Config, watch_dir: Path, known: set[str]) -> None:
    """Polling fallback when inotifywait is unavailable."""
    while True:
        await asyncio.sleep(5)
        try:
            current = {f.name for f in watch_dir.iterdir()
                       if f.suffix == ".md" and not f.name.endswith(".tmp.md")}
        except FileNotFoundError:
            continue

        new = current - known
        if new:
            for name in sorted(new):
                known.add(name)
                await _handle_new_doc(config, watch_dir / name)


async def _handle_new_doc(config: Config, doc_path: Path) -> None:
    """Trigger QCF for a newly detected design document."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] New design doc: {doc_path.name}")

    _emit_event(config, "pipeline.start",
                 design_doc=str(doc_path),
                 started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                 max_rounds=config.max_rounds)

    engine = QCFEngine(config)
    await engine.run(doc_path, max_rounds=config.max_rounds)

    print(f"[{ts}] Pipeline finished for: {doc_path.name}\n")
