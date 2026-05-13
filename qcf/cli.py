"""CLI for The Quad-Core Flow (QCF)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .config import Config, write_default_config
from .engine import QCFEngine
from .watch import watch_mode

_PID_FILE = Path("/tmp/qcf-pid.txt")


def _stop() -> None:
    """Kill all running QCF processes."""
    # Kill from PID file first (cleanest)
    if _PID_FILE.exists():
        try:
            pid = int(_PID_FILE.read_text().strip())
            os.kill(pid, 15)  # SIGTERM
            _PID_FILE.unlink()
            print(f"QCF (PID {pid}) stopped.")
        except (ProcessLookupError, ValueError, OSError):
            _PID_FILE.unlink()
    # Fallback: kill by process name
    os.system("pkill -f 'qcf auto|qcf run' 2>/dev/null")
    os.system("pkill -f 'qcf watch|inotifywait' 2>/dev/null")
    print("All QCF processes stopped.")


def _determine_start_stage(doc_path: str) -> str:
    """Infer starting stage from the document's directory."""
    if "/tech-lead/" in doc_path:
        return "implement"
    if "/code-reviewer/" in doc_path or "/security-reviewer/" in doc_path:
        return "fix"
    print(f"Warning: cannot determine starting stage from path: {doc_path}")
    print("Defaulting to 'implement'. Place docs in tech-lead/, code-reviewer/, or security-reviewer/.")
    return "implement"


def _cmd_init(args: argparse.Namespace) -> None:
    target = Path(args.path)
    if target.exists() and not args.force:
        print(f"Config already exists: {target}")
        print("Use --force to overwrite.")
        return
    write_default_config(target)
    print(f"Created default config: {target}")

    # Create default directory structure
    cfg = Config.load(target, cwd=Path.cwd())
    dirs = [
        ("Tech-Lead docs", cfg.tech_lead_dir),
        ("Coder workspace", cfg.coder_dir),
        ("Code-Reviewer docs", cfg.code_reviewer_dir),
        ("Security-Reviewer docs", cfg.security_reviewer_dir),
        ("Fail reports", cfg.fail_dir),
        ("Task files", cfg.task_dir),
    ]
    created = []
    for label, path in dirs:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            gitkeep = path / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.write_text("")
            created.append((label, path))
        elif not any(path.iterdir()):
            # Exists but empty — still flag it
            gitkeep = path / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.write_text("")
            created.append((label, path))

    if created:
        print()
        print("Created directories:")
        for label, path in created:
            print(f"  {label:20s}  {path}")
    else:
        print("All directories already exist.")

    # Sample task if tasks/ is empty
    sample = cfg.task_dir / "example.md"
    if not sample.exists():
        sample.write_text(
            "# Example Task\n\n"
            "Describe the feature or bug to fix here.\n\n"
            "## Requirements\n"
            "- What should the implementation achieve?\n"
            "- Any constraints or preferences?\n"
        )
        print(f"  {'Sample task':20s}  {sample}")

    print()
    print("Next steps:")
    print(f"  1. Write a task:      echo '# my task' > {cfg.task_dir / 'my-task.md'}")
    print(f"  2. Run auto mode:     qcf auto {cfg.task_dir / 'my-task.md'}")
    print(f"  Or write a design doc directly:")
    print(f"     qcf run {cfg.tech_lead_dir / 'design.md'}")


def _cmd_run(args: argparse.Namespace) -> None:
    cfg = Config.load(args.config, cwd=Path.cwd())
    design_doc = Path(args.design_doc)

    if not design_doc.exists():
        print(f"Error: document not found: {design_doc}")
        sys.exit(1)

    # Determine starting stage
    if args.start_stage:
        start_stage = args.start_stage
    else:
        start_stage = _determine_start_stage(str(design_doc))

    max_rounds = args.max_rounds or cfg.max_rounds

    print(f"Entry stage: {start_stage} | Max rounds: {max_rounds}")

    if args.detach:
        _run_detached(design_doc, max_rounds, start_stage, args.config)
        return

    engine = QCFEngine(cfg)
    success = asyncio.run(engine.run(design_doc, max_rounds=max_rounds, start_stage=start_stage))
    sys.exit(0 if success else 1)


def _run_detached(design_doc: Path, max_rounds: int, start_stage: str, config_path: str | None) -> None:
    """Fork QCF into a background process so the caller can poll status."""
    cmd = [
        sys.executable, "-m", "qcf", "run", str(design_doc),
        "--max-rounds", str(max_rounds),
        "--start-stage", start_stage,
    ]
    if config_path:
        cmd.extend(["--config", config_path])

    log_file = Path("/tmp/qcf-detach.log")
    with open(log_file, "a") as f:
        f.write(f"\n--- Pipeline started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

    proc = subprocess.Popen(
        cmd,
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _PID_FILE.write_text(str(proc.pid))
    os.chmod(_PID_FILE, 0o600)
    print(f"\nQCF started in background (PID {proc.pid})")
    print(f"├─ Output:   tail -f /tmp/qcf-detach.log")
    print(f"├─ Monitor:  qcf status --watch")
    print(f"├─ Poll:     cat /tmp/qcf-status.json")
    print(f"└─ Stop:     qcf stop")


def _cmd_auto(args: argparse.Namespace) -> None:
    """Quad-Core Flow: Tech-Lead → implementing → review → security (+ Scout if continuous)."""
    cfg = Config.load(args.config, cwd=Path.cwd())
    task_path = Path(args.task)

    if not task_path.exists():
        print(f"Error: task not found: {task_path}")
        sys.exit(1)

    max_rounds = args.max_rounds or cfg.max_rounds
    engine = QCFEngine(cfg)

    if args.detach:
        _run_detached_auto(task_path, max_rounds, args.continuous, args.config)
        return

    if args.continuous:
        print(f"⚡ The Quad-Core Flow — Continuous Mode")
        print(f"   Task: {task_path.name} | Max inner rounds: {max_rounds}")
        asyncio.run(engine.run_continuous(task_path))
    else:
        print(f"⚡ The Quad-Core Flow — Single Task")
        print(f"   Task: {task_path.name} | Max inner rounds: {max_rounds}")
        # Step 1: Tech-Lead
        design_doc = _run_tech_lead_stage(cfg, task_path)
        if not design_doc:
            print("Tech-Lead failed — aborting.")
            sys.exit(1)
        # Step 2: Inner loop
        success = asyncio.run(engine.run(design_doc, max_rounds=max_rounds))
        sys.exit(0 if success else 1)


def _run_tech_lead_stage(cfg: Config, task_path: Path) -> Path | None:
    """Synchronous wrapper for Tech-Lead stage."""
    import asyncio
    from .engine import _run_tech_lead
    return asyncio.run(_run_tech_lead(cfg, task_path))


def _run_detached_auto(task_path: Path, max_rounds: int, continuous: bool, config_path: str | None) -> None:
    """Launch auto mode in background."""
    cmd = [
        sys.executable, "-m", "qcf", "auto", str(task_path),
        "--max-rounds", str(max_rounds),
    ]
    if continuous:
        cmd.append("--continuous")
    if config_path:
        cmd.extend(["--config", config_path])

    log_file = Path("/tmp/qcf-detach.log")
    with open(log_file, "a") as f:
        f.write(f"\n--- Quad-Core Flow auto started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")

    proc = subprocess.Popen(
        cmd,
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _PID_FILE.write_text(str(proc.pid))
    os.chmod(_PID_FILE, 0o600)
    print(f"\nQuad-Core Flow started in background (PID {proc.pid})")
    print(f"├─ Output:   tail -f /tmp/qcf-detach.log")
    print(f"├─ Poll:     cat /tmp/qcf-status.json")
    print(f"└─ Stop:     qcf stop")


def _cmd_watch(args: argparse.Namespace) -> None:
    cfg = Config.load(args.config, cwd=Path.cwd())
    try:
        asyncio.run(watch_mode(cfg))
    except KeyboardInterrupt:
        print("\nWatch stopped.")


def _cmd_stop(args: argparse.Namespace) -> None:
    _stop()


def _cmd_version(args: argparse.Namespace) -> None:
    print(_get_version_string())


# ── Config command ─────────────────────────────────────────────

def _load_toml_safe(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    with open(path, "rb") as f:
        return tomllib.load(f)


_CONFIG_SECTIONS: dict[str, str] = {
    # section_name: the header we look for in qcf.toml
    "workspace": "workspace",
    "stages": "stages",
    "models": "models",
    "paths": "paths",
    "files": "files",
    "commit": "commit",
    "claude": "claude",
    "hooks": "hooks",
}


def _cmd_config(args: argparse.Namespace) -> None:
    cfg_path = Path(args.config_file) if args.config_file else Path("qcf.toml")
    if not cfg_path.exists():
        print(f"Error: config file not found: {cfg_path}")
        print("Create one with: qcf init")
        sys.exit(1)

    if args.action == "get":
        data = _load_toml_safe(cfg_path)

        if args.key:
            # Single key: section.field (e.g. models.review)
            parts = args.key.split(".", 1)
            section = parts[0]
            field = parts[1] if len(parts) > 1 else None

            if section not in data:
                print(f"Section [{section}] not found in {cfg_path}")
                sys.exit(1)

            if field:
                if field not in data[section]:
                    print(f"Key '{field}' not found in section [{section}]")
                    sys.exit(1)
                val = data[section][field]
                if isinstance(val, str):
                    print(val)
                elif isinstance(val, list):
                    print(" ".join(val))
                else:
                    print(val)
            else:
                # List entire section
                print(f"[{section}]")
                for k, v in data[section].items():
                    print(f"  {k} = {v}")
        else:
            # No key → dump everything
            for section, fields in data.items():
                if isinstance(fields, dict):
                    print(f"[{section}]")
                    for k, v in fields.items():
                        if isinstance(v, list):
                            print(f"  {k} = [{' '.join(v)}]")
                        else:
                            print(f"  {k} = {v}")
                    print()
                else:
                    print(f"{section} = {fields}")

    elif args.action == "set":
        if not args.key or not args.value:
            print("Usage: qcf config set <section.key> <value>")
            sys.exit(1)

        parts = args.key.split(".", 1)
        if len(parts) != 2:
            print("Key must be in the form: section.field  (e.g. models.review)")
            sys.exit(1)

        section, field = parts
        value = args.value

        # Read file lines for editing
        lines = cfg_path.read_text().splitlines(keepends=True)

        # Try to detect if value should be a number, bool, or quoted string
        if value.lower() in ("true", "false"):
            toml_val = value.lower()
        elif value.isdigit():
            toml_val = value
        else:
            toml_val = f'"{value}"'

        section_header = f"[{section}]"
        in_section = False
        found = False
        insert_at = -1

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Track section boundaries
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_section:
                    # We left the target section without finding the key → insert
                    break
                in_section = (stripped == section_header)
                if in_section:
                    insert_at = i + 1  # Right after header
                continue

            if in_section and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key == field:
                    indent = line[:len(line) - len(line.lstrip())]
                    lines[i] = f"{indent}{field} = {toml_val}\n"
                    found = True
                    break

        if not found:
            if insert_at >= 0:
                indent = " " * max(0, len(section_header) - len(section_header.lstrip()) + 4)
                lines.insert(insert_at, f"{indent}{field} = {toml_val}\n")
            else:
                # Section doesn't exist — append
                lines.append(f"\n{section_header}\n")
                lines.append(f"{field} = {toml_val}\n")

        cfg_path.write_text("".join(lines))
        print(f"✅ {section}.{field} = {value}")


def _cmd_status(args: argparse.Namespace) -> None:
    status_file = Config.load(args.config, cwd=Path.cwd()).status_file

    if not status_file.exists():
        print(f"No QCF status found ({status_file})")
        print("Start a QCF run first with: qcf run <design-doc>")
        sys.exit(1)

    if args.watch:
        _watch_status(status_file)
        return

    # One-shot display
    data = json.loads(status_file.read_text())
    print(_format_status(data))


def _watch_status(path: Path) -> None:
    """Continuously monitor the status file for changes."""
    last_content = ""
    try:
        while True:
            if path.exists():
                content = path.read_text()
                if content != last_content:
                    last_content = content
                    try:
                        data = json.loads(content)
                        os.system("clear")
                        print(_format_status(data))
                    except (json.JSONDecodeError, Exception):
                        print(f"[{time.strftime('%H:%M:%S')}] (status file updating...)")
            else:
                os.system("clear")
                print(f"Pipeline status file not found: {path}")
                print("Waiting for QCF to start...")

            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStatus watch stopped.")


def _format_status(data: dict) -> str:
    _G = "\033[32m"  # green
    _R = "\033[31m"  # red
    _B = "\033[1m"   # bold
    _X = "\033[0m"   # reset

    def _c(result: str) -> str:
        """Colorize a result token."""
        if result == "PASS":
            return f"{_G}{result}{_X}"
        if result in ("FAIL", "TIMEOUT"):
            return f"{_R}{result}{_X}"
        return result

    lines = []
    lines.append(f"{_B}{'=' * 50}{_X}")
    lines.append(f"  {_B}⚡ Quad-Core Flow{_X}  {data.get('_updated_at', '')}")
    lines.append(f"{_B}{'=' * 50}{_X}")
    lines.append(f"  Stage:     {data.get('current_stage', 'N/A')}")
    lines.append(f"  Round:     {data.get('current_round', 'N/A')}/{data.get('max_rounds', 'N/A')}")

    doc = data.get("design_doc", "")
    if doc:
        lines.append(f"  Document:  {Path(doc).name}")

    if data.get("started_at"):
        lines.append(f"  Started:   {data['started_at']}")

    history = data.get("history", [])
    if history:
        lines.append(f"  {'─' * 48}")
        for h in history:
            stage = h.get("stage", "?")
            result = h.get("result", "?")
            inp = h.get("input_tokens", 0)
            out = h.get("output_tokens", 0)
            icon = {"PASS": "✓", "FAIL": "✗", "TIMEOUT": "⏱", "SKIP": "→"}.get(result, "?")
            summary = h.get("summary", "")
            colored_res = _c(result)
            colored_icon = _c(icon) if result in ("PASS", "FAIL", "TIMEOUT") else icon
            if inp or out:
                lines.append(f"  {colored_icon} {stage:<12s} {colored_res:<8s} {inp:>6,} in / {out:>6,} out")
            else:
                lines.append(f"  {colored_icon} {stage:<12s} {colored_res:<8s}")

    final = data.get("final_result")
    if final:
        lines.append(f"  {'─' * 48}")
        colored_final = _c("PASS") if "PASS" in final else (_c("FAIL") if "FAIL" in final else final)
        lines.append(f"  Final:     {colored_final}")

    lines.append(f"{_B}{'=' * 50}{_X}")
    return "\n".join(lines)


def _get_version_string() -> str:
    """Return the version string for the --version flag."""
    try:
        from importlib.metadata import version
        v = version("qcf")
    except Exception:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        try:
            from pathlib import Path
            pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
            data = tomllib.loads(pyproject.read_text())
            v = data["project"]["version"]
        except Exception:
            v = "0.0.0"
    return f"qcf {v}"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qcf",
        description="The Quad-Core Flow — tech-lead → coder → reviewer → security",
    )
    parser.add_argument("--config", "-c", help="Path to qcf.toml (default: CWD/qcf.toml)")
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=_get_version_string(),
        help="Show version and exit",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Create default qcf.toml and directory structure")
    p_init.add_argument("path", nargs="?", default="qcf.toml",
                        help="Target path (default: qcf.toml)")
    p_init.add_argument("--force", "-f", action="store_true",
                        help="Overwrite existing config")

    # run
    p_run = sub.add_parser("run", help="Run inner loop on a design document (Core 2-4)")
    p_run.add_argument("design_doc", help="Path to the design document (.md)")
    p_run.add_argument("--max-rounds", "-r", type=int, default=0,
                       help="Override max rounds from config")
    p_run.add_argument("--start-stage", "-s",
                       choices=["implement", "fix"],
                       help="Override starting stage detection")
    p_run.add_argument("--detach", "-d", action="store_true",
                       help="Run in background; poll /tmp/qcf-status.json for progress")

    # auto
    p_auto = sub.add_parser("auto", help="Quad-Core Flow: tech-lead → coder → review → security")
    p_auto.add_argument("task", help="High-level task description (.md)")
    p_auto.add_argument("--continuous", "-c", action="store_true",
                        help="After completion, scout for new tasks and continue iterating")
    p_auto.add_argument("--max-rounds", "-r", type=int, default=0,
                        help="Override max rounds from config")
    p_auto.add_argument("--detach", "-d", action="store_true",
                        help="Run in background")

    # watch
    sub.add_parser("watch", help="Watch tech-lead/ directory for new docs")

    # status
    p_status = sub.add_parser("status", help="Show QCF status (or --watch for live view)")
    p_status.add_argument("--watch", "-w", action="store_true",
                          help="Continuously monitor status file")

    # stop
    sub.add_parser("stop", help="Kill all running QCF processes")

    # version
    sub.add_parser("version", help="Show version and exit")

    # config — get/set configuration values
    p_config = sub.add_parser("config", help="Get or set configuration values in qcf.toml")
    p_config.add_argument("action", choices=["get", "set"],
                           help="Get a value or set a value")
    p_config.add_argument("key", nargs="?",
                           help="Config key (e.g. models.review, stages.review_timeout)")
    p_config.add_argument("value", nargs="?",
                           help="New value (for 'set' action)")
    p_config.add_argument("--config-file", "-c",
                           help="Path to qcf.toml (default: CWD/qcf.toml)")

    args = parser.parse_args()

    if args.command == "init":
        _cmd_init(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "auto":
        _cmd_auto(args)
    elif args.command == "watch":
        _cmd_watch(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "stop":
        _cmd_stop(args)
    elif args.command == "config":
        _cmd_config(args)
    elif args.command == "version":
        _cmd_version(args)


if __name__ == "__main__":
    main()
