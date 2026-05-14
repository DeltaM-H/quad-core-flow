"""QCF state machine — tech-lead → implement → review + audit → pilot."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .models import (
    ActionSuggestion,
    AuditOutput,
    Issue,
    ReviewOutput,
    RoundStageMetric,
    RoundsOverview,
    extract_audit_result,
    extract_action_suggestion,
    extract_review_result,
)
from .progress import AgentProgress
from . import prompts
from .hooks import Hooks
from .runner import run_claude


# ══════════════════════════════════════════════════════════════
# ANSI color helpers
# ══════════════════════════════════════════════════════════════

_GC = "\033[32m"   # green
_RC = "\033[31m"   # red
_BC = "\033[1m"    # bold
_XC = "\033[0m"    # reset


def _green(s: str) -> str:
    return f"{_GC}{s}{_XC}"


def _red(s: str) -> str:
    return f"{_RC}{s}{_XC}"


def _bold(s: str) -> str:
    return f"{_BC}{s}{_XC}"


def _color_result(result: str) -> str:
    if result == "PASS":
        return _green(result)
    if result in ("FAIL", "TIMEOUT"):
        return _red(result)
    return result


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_safe(path: Path) -> str:
    if path.exists():
        return path.read_text("utf-8", errors="replace")
    return f"(file not found: {path})"


_SUMMARY_PATTERN = re.compile(
    r"PROJECT_SUMMARY_START\s*\n(.*?)\n\s*PROJECT_SUMMARY_END",
    re.DOTALL,
)


def _extract_project_summary(text: str) -> str:
    """Extract the PROJECT_SUMMARY block from Pilot output."""
    m = _SUMMARY_PATTERN.search(text)
    if m:
        return m.group(1).strip()[:2000]  # hard cap at 2KB
    return ""


def _save_report(text: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)


def _git(cmd: list[str], cwd: Path | None = None) -> int:
    return subprocess.run(cmd, cwd=cwd).returncode


# ══════════════════════════════════════════════════════════════
# Status JSON writer
# ══════════════════════════════════════════════════════════════

def _write_status(status_file: Path, data: dict[str, Any]) -> None:
    prev: dict[str, Any] = {}
    if status_file.exists():
        try:
            prev = json.loads(status_file.read_text())
        except (json.JSONDecodeError, Exception):
            pass
    for key in ("design_doc", "started_at", "max_rounds"):
        if key in prev and key not in data:
            data[key] = prev[key]
    data["_updated_at"] = _timestamp()
    try:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        os.chmod(status_file, 0o600)
    except OSError as e:
        print(f"  [warn] cannot write status file: {e}")


# ══════════════════════════════════════════════════════════════
# Stage runners
# ══════════════════════════════════════════════════════════════

async def _run_implement(
    cfg: Config,
    design_doc: Path,
    round_num: int,
) -> tuple[str, Any]:  # returns (result_text, StageMetrics)
    _write_status(cfg.status_file, {
        "current_round": round_num,
        "current_stage": "implement (running)",
    })
    prompt_text = prompts.implement_prompt(
        design_doc_path=str(design_doc),
    )
    log_path = cfg.log_dir / f"qcf-implement-{round_num:02d}.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.implement_timeout,
        model=cfg.model_for("implement"),
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        max_output_tokens=cfg.max_output_tokens,
        thinking_budget=cfg.thinking_budget,
        cwd=cfg.root_dir,
    )
    _write_status(cfg.status_file, {
        "current_round": round_num,
        "current_stage": f"implement ({'TIMEOUT' if metrics.timed_out else 'PASS'})",
    })
    return result_text, metrics


async def _run_tech_lead(cfg: Config, task_path: Path, summary_pack: str = "") -> Path | None:
    """Core 1: Tech-Lead — analyze project and produce a design document."""
    _write_status(cfg.status_file, {
        "current_round": 1,
        "current_stage": "tech-lead (running)",
    })

    task_description = task_path.read_text("utf-8", errors="replace")
    tree = prompts.project_tree(cwd=cfg.root_dir)

    # Determine output path
    design_name = f"{task_path.stem}-design.md"
    cfg.tech_lead_dir.mkdir(parents=True, exist_ok=True)
    design_doc = cfg.tech_lead_dir / design_name

    prompt_text = prompts.tech_lead_prompt(
        task_description=task_description,
        design_doc_path=str(design_doc),
        project_tree_str=tree,
        summary_pack=summary_pack,
    )
    log_path = cfg.log_dir / "qcf-tech-lead.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.tech_lead_timeout,
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        max_output_tokens=cfg.max_output_tokens,
        thinking_budget=cfg.thinking_budget,
        cwd=cfg.root_dir,
    )

    success = not metrics.timed_out and design_doc.exists()
    _write_status(cfg.status_file, {
        "current_round": 0,
        "current_stage": f"tech-lead ({'PASS' if success else 'FAIL'})",
    })
    tag = _green("PASS") if success else _red("FAIL")
    print(f"  ⚡ Tech-Lead: {tag} | {design_doc.name}")
    print(f"[QCF] stage: tech-lead → {'PASS' if success else 'FAIL'}")

    return design_doc if success else None


async def _run_pilot(cfg: Config, last_task: str = "",
                     round_history: list[str] | None = None) -> tuple[str, str]:
    """Core 5: Pilot — assess project, extract structured summary, decide next step.

    Returns:
        ``(verdict, project_summary)`` where:
        - verdict is ``"STEADY_STATE"`` or a path to a new task file.
        - project_summary is the extracted PROJECT_SUMMARY block (or empty string).
    """
    _write_status(cfg.status_file, {
        "current_round": 0,
        "current_stage": "pilot (running)",
    })

    tree = prompts.project_tree(cwd=cfg.root_dir, max_depth=4)
    cfg.task_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = prompts.pilot_prompt(
        project_tree_str=tree,
        last_task=last_task,
        round_history=round_history or [],
        task_output_path=str(cfg.pilot_task_file),
    )
    log_path = cfg.log_dir / "qcf-pilot.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.pilot_timeout,
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        max_output_tokens=cfg.max_output_tokens,
        thinking_budget=cfg.thinking_budget,
        cwd=cfg.root_dir,
    )

    # Extract structured project summary from Pilot output
    project_summary = _extract_project_summary(result_text)
    if project_summary:
        try:
            cfg.summary_pack_file.parent.mkdir(parents=True, exist_ok=True)
            cfg.summary_pack_file.write_text(project_summary)
            os.chmod(cfg.summary_pack_file, 0o600)
        except OSError:
            pass

    # Clean up pilot task output if it exists
    verdict = "STEADY_STATE"
    new_task: Path | None = None
    if cfg.pilot_task_file.exists():
        content = cfg.pilot_task_file.read_text().strip()
        if "STEADY_STATE" not in content:
            # Write as a new task file
            task_name = f"pilot-{time.strftime('%Y%m%d-%H%M%S')}.md"
            new_task = cfg.task_dir / task_name
            cfg.task_dir.mkdir(parents=True, exist_ok=True)
            new_task.write_text(content)
            verdict = str(new_task)
        cfg.pilot_task_file.unlink(missing_ok=True)

    verdict_tag = "STEADY_STATE" if verdict == "STEADY_STATE" else "NEW_TASK"
    print(f"  ⚡ Pilot: {'🟢 STEADY_STATE' if verdict == 'STEADY_STATE' else '🔄 new task: ' + verdict}")
    print(f"[QCF] stage: pilot → {verdict_tag}")
    return verdict, project_summary


async def _run_fix(
    cfg: Config,
    design_doc: Path,
    round_num: int,
) -> tuple[str, Any]:
    _write_status(cfg.status_file, {
        "current_round": round_num,
        "current_stage": "fix (running)",
    })

    issues_content = _read_safe(cfg.issues_file) if cfg.issues_file.exists() else "(问题列表文件不存在)"

    prompt_text = prompts.fix_prompt(
        design_doc_path=str(design_doc),
        issues_content=issues_content,
    )
    log_path = cfg.log_dir / f"qcf-fix-{round_num:02d}.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.fix_timeout,
        model=cfg.model_for("fix"),
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        max_output_tokens=cfg.max_output_tokens,
        thinking_budget=cfg.thinking_budget,
        cwd=cfg.root_dir,
    )
    _write_status(cfg.status_file, {
        "current_round": round_num,
        "current_stage": f"fix ({'TIMEOUT' if metrics.timed_out else 'PASS'})",
    })
    return result_text, metrics


async def _run_review(
    cfg: Config,
    design_doc: Path,
    round_num: int,
) -> ReviewOutput:
    prompt_text = prompts.review_prompt(
        round_num=round_num,
        design_doc_path=str(design_doc),
        issues_file=str(cfg.review_issues_file),
    )
    log_path = cfg.log_dir / f"qcf-review-{round_num:02d}.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.review_timeout,
        model=cfg.model_for("review"),
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        max_output_tokens=cfg.max_output_tokens,
        thinking_budget=cfg.thinking_budget,
        cwd=cfg.root_dir,
    )

    result, summary = extract_review_result(result_text)
    if not result:
        result = "FAIL"
        summary = summary or "[结果解析失败]"

    issues: list[Issue] = []
    if cfg.review_issues_file.exists():
        for line in cfg.review_issues_file.read_text().strip().split("\n"):
            issue = Issue.from_line(line)
            if issue:
                issues.append(issue)

    colored_res = _color_result(result) + (_red(" | TIMEOUT") if metrics.timed_out else "")
    print(f"  ⚡ Review: {colored_res} | {metrics.input_tokens} in / {metrics.output_tokens} out")
    print(f"     ↳ {summary[:120]}")

    return ReviewOutput(result=result, summary=summary, issues=issues)


async def _run_audit(
    cfg: Config,
    design_doc: Path,
    round_num: int,
) -> AuditOutput:
    prompt_text = prompts.audit_prompt(
        round_num=round_num,
        design_doc_path=str(design_doc),
        issues_file=str(cfg.audit_issues_file),
    )
    log_path = cfg.log_dir / f"qcf-audit-{round_num:02d}.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.audit_timeout,
        model=cfg.model_for("audit"),
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        max_output_tokens=cfg.max_output_tokens,
        thinking_budget=cfg.thinking_budget,
        cwd=cfg.root_dir,
    )

    result, summary = extract_audit_result(result_text)
    if not result:
        result = "FAIL"
        summary = summary or "[结果解析失败]"

    issues: list[Issue] = []
    if cfg.audit_issues_file.exists():
        for line in cfg.audit_issues_file.read_text().strip().split("\n"):
            issue = Issue.from_line(line)
            if issue:
                issues.append(issue)

    # Parse action_suggestion from result_text directly (not from log file)
    action_suggestion = extract_action_suggestion(result_text)

    colored_res = _color_result(result) + (_red(" | TIMEOUT") if metrics.timed_out else "")
    print(f"  ⚡ Audit: {colored_res} | {metrics.input_tokens} in / {metrics.output_tokens} out")
    print(f"     ↳ {summary[:120]}")

    return AuditOutput(result=result, summary=summary, vulnerabilities=issues,
                       action_suggestion=action_suggestion)


# ══════════════════════════════════════════════════════════════
# Commit & fail report
# ══════════════════════════════════════════════════════════════

def _auto_commit(cfg: Config, round_num: int, stage_name: str = "implement") -> None:
    if not cfg.commit_enabled:
        print("  [auto-commit disabled by config]")
        return

    print("  [auto-commit]...")
    # Stage-specific file patterns
    if stage_name == "tech-lead":
        ret = _git(["git", "add", cfg.tech_lead_dir.name + "/"], cwd=cfg.root_dir)
    else:
        ret = _git(["git", "add", "-A"], cwd=cfg.root_dir)
    if ret != 0:
        print("  → git add failed, skipping commit")
        return

    ret = _git(["git", "diff", "--cached", "--quiet"], cwd=cfg.root_dir)
    if ret == 0:
        print("  → Nothing to commit.")
        return

    msg = cfg.commit_message_stage(stage_name, round_num)
    ret = subprocess.run(["git", "commit", "-m", msg], cwd=cfg.root_dir).returncode
    print("  → Committed." if ret == 0 else "  → Commit failed.")


def _write_fail_report(cfg: Config, round_num: int, review: ReviewOutput, audit: AuditOutput) -> str:
    """Print fail analysis to session and write report file."""
    cfg.fail_dir.mkdir(parents=True, exist_ok=True)
    report_path = cfg.fail_dir / f"{round_num:02d}-fail-report-v1.0.md"

    lines: list[str] = [
        "# Pipeline Fail Report\n",
        f"- **Round**: {round_num}",
        f"- **Review**: {review.result}",
        f"- **Audit**: {audit.result}\n",
        "## Review Issues\n",
    ]
    if review.issues:
        for i in review.issues:
            lines.append(f"- [{i.severity}] `{i.file}`: {i.description}")
    else:
        lines.append("(no detailed issue list)")

    lines.extend(["\n## Audit Issues\n"])
    if audit.vulnerabilities:
        for v in audit.vulnerabilities:
            lines.append(f"- [{v.severity}] `{v.file}`: {v.description}")
    else:
        lines.append("(no detailed issue list)")

    lines.append(f"\n## Fail Summary\n")
    lines.append(f"QCF failed at round {round_num}/{cfg.max_rounds}.")
    lines.append(f"Review: {review.result} — {review.summary}" if review.summary else f"Review: {review.result}")
    lines.append(f"Audit: {audit.result} — {audit.summary}" if audit.summary else f"Audit: {audit.result}")

    report_text = "\n".join(lines)

    # Print detailed analysis to session
    print(f"\n{'=' * 50}")
    print(f"  {_red('❌ QCF FAILED')} — Round {round_num}/{cfg.max_rounds}")
    print(f"{'=' * 50}")
    print(f"  Review: {review.result}")
    if review.summary:
        print(f"  Summary: {review.summary}")
    if review.issues:
        print(f"\n  ── Review Issues ({len(review.issues)}) ──")
        for i in review.issues:
            print(f"    [{i.severity.upper()}] {i.file}: {i.description}")
    print(f"\n  Audit: {audit.result}")
    if audit.summary:
        print(f"  Summary: {audit.summary}")
    if audit.vulnerabilities:
        print(f"\n  ── Audit Issues ({len(audit.vulnerabilities)}) ──")
        for v in audit.vulnerabilities:
            print(f"    [{v.severity.upper()}] {v.file}: {v.description}")
    print(f"{'=' * 50}")

    report_path.write_text(report_text)
    print(f"\n  → Fail report: {report_path}")
    return report_text


def _save_final_reports(cfg: Config, round_num: int, final_result: str) -> None:
    """Write review+audit reports only at the very end."""
    review_log = cfg.log_dir / f"qcf-review-{round_num:02d}.log"
    out = cfg.out_review_dir / f"round-{round_num:02d}-review-v1.0.md"
    _save_report(_read_safe(review_log), out)

    audit_log = cfg.log_dir / f"qcf-audit-{round_num:02d}.log"
    out = cfg.out_audit_dir / f"round-{round_num:02d}-audit-v1.0.md"
    _save_report(_read_safe(audit_log), out)

    print(f"\n  → Review report: {cfg.out_review_dir / f'round-{round_num:02d}-review-v1.0.md'}")
    print(f"  → Audit report: {cfg.out_audit_dir / f'round-{round_num:02d}-audit-v1.0.md'}")
    print(f"  → Final result: {final_result}")


def _write_summary_pack(
    cfg: Config,
    new_task: Path,
    round_history: list[str],
) -> str:
    """Write a compact summary pack for the next Tech-Lead iteration.

    Extracts key classes, imports, and recent results from the project,
    writing to ``/tmp/qcf-summary-pack.json`` (hard cap at 10 KB).

    Returns:
        The summary content as a string (for passing to Tech-Lead in-process),
        or empty string on failure.
    """
    import json
    import subprocess

    summary: dict[str, object] = {
        "new_task": new_task.name,
        "task_description": new_task.read_text("utf-8", errors="replace")[:2000],
        "recent_history": round_history[-10:],
    }

    # Extract top-level module/class names from qcf/
    try:
        result = subprocess.run(
            ["find", "qcf", "-name", "*.py", "-maxdepth", 2],
            capture_output=True, text=True, timeout=10,
            cwd=str(cfg.root_dir),
        )
        summary["qcf_modules"] = [l.strip() for l in result.stdout.split("\n") if l.strip()]
    except Exception:
        summary["qcf_modules"] = []

    # Extract key imports from qcf/*.py
    imports: list[str] = []
    try:
        for py_file in cfg.root_dir.glob("qcf/*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text("utf-8", errors="replace")
            for line in content.split("\n"):
                if line.startswith("import ") or line.startswith("from "):
                    imports.append(f"{py_file.name}: {line.strip()}")
        summary["key_imports"] = imports[:30]  # Cap at 30 lines
    except Exception:
        summary["key_imports"] = []

    summary_text = json.dumps(summary, ensure_ascii=False, indent=2, default=str)

    # Hard cap at 10 KB
    if len(summary_text) > 10240:
        summary_text = summary_text[:10240] + '\n...\n}'

    # Write to file (truncated)
    try:
        cfg.summary_pack_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.summary_pack_file.write_text(summary_text)
    except OSError:
        pass

    return summary_text


# ══════════════════════════════════════════════════════════════
# Progress Reporter — lifecycle hooks for QCF events
# ══════════════════════════════════════════════════════════════

class ProgressReporter:
    """Lifecycle callbacks for QCF progress. All return sequence of status lines."""

    def on_start(self, design_doc: Path, max_rounds: int) -> list[str]:
        return [
            _bold("=" * 46),
            f" {_bold('⚡ Quad-Core Flow')}",
            f" Core 2-4: {design_doc}",
            f" Max Rounds: {max_rounds}",
            _bold("=" * 46),
        ]

    def on_stage_start(self, round_num: int, max_rounds: int, stage: str) -> list[str]:
        return [f"── Round {round_num:02d}/{max_rounds} ──", f"  [{stage}]..."]

    def on_stage_end(self, round_num: int, stage: str, metrics: RoundStageMetric) -> list[str]:
        line = f"    输入:{metrics.input_tokens:,} | 输出:{metrics.output_tokens:,}"
        if metrics.timed_out:
            line += " | ⏱ TIMEOUT"
        return [line]

    def on_round_result(
        self, round_num: int, max_rounds: int,
        review: ReviewOutput, audit: AuditOutput,
    ) -> list[str]:
        lines = [f"  ⚡ Review: {_color_result(review.result)} | {review.summary[:120] if review.summary else ''}"]
        lines.append(f"  ⚡ Audit:  {_color_result(audit.result)} | {audit.summary[:120] if audit.summary else ''}")
        return lines

    def on_passed(self, round_num: int, review: ReviewOutput, audit: AuditOutput) -> list[str]:
        return [
            "",
            "=" * 46,
            f"  {_green('✅')} {_bold(f'Quad-Core Flow PASSED — round {round_num}')}",
            "=" * 46,
        ]

    def on_failed(self, round_num: int, max_rounds: int,
                   review: ReviewOutput, audit: AuditOutput) -> list[str]:
        lines = [
            "",
            _bold("=" * 46),
            f"  {_red('❌')} Round {round_num} failed — review={_color_result(review.result)}, audit={_color_result(audit.result)}",
            _bold("=" * 46),
        ]
        if review.issues:
            lines.append("  Review issues:")
            for i in review.issues:
                lines.append(f"    [{i.severity}] {i.file}: {i.description}")
        if audit.vulnerabilities:
            lines.append("  Audit issues:")
            for v in audit.vulnerabilities:
                lines.append(f"    [{v.severity}] {v.file}: {v.description}")
        return lines

    def on_exhausted(self, round_num: int, max_rounds: int,
                      last_review: ReviewOutput, last_audit: AuditOutput,
                      fail_report: str) -> list[str]:
        return [
            "",
            "=" * 46,
            f"  {_red('⛔')} {_bold(f'Quad-Core Flow exhausted — max rounds ({max_rounds}) reached')}",
            f"  Last review: {_color_result(last_review.result)}",
            f"  Last audit:  {_color_result(last_audit.result)}",
            "=" * 46,
            f"  Fail report: {fail_report}",
        ]

    def on_error(self, msg: str) -> list[str]:
        return [f"  Error: {msg}"]


class StdoutReporter(ProgressReporter):
    """Default reporter — prints to stdout immediately."""

    def on_start(self, design_doc: Path, max_rounds: int) -> list[str]:
        lines = super().on_start(design_doc, max_rounds)
        for l in lines:
            print(l)
        return lines

    def on_stage_start(self, round_num: int, max_rounds: int, stage: str) -> list[str]:
        if stage == "review":
            print("  [review + audit]...")
            return ["  [review + audit]..."]
        lines = super().on_stage_start(round_num, max_rounds, stage)
        for l in lines:
            print(l)
        return lines

    def on_stage_end(self, round_num: int, stage: str, metrics: RoundStageMetric) -> list[str]:
        # implemented by RoundStageMetric later
        return []

    def on_round_result(self, round_num: int, max_rounds: int,
                         review: ReviewOutput, audit: AuditOutput) -> list[str]:
        lines = super().on_round_result(round_num, max_rounds, review, audit)
        for l in lines:
            print(l)
        return lines

    def on_passed(self, round_num: int, review: ReviewOutput, audit: AuditOutput) -> list[str]:
        lines = super().on_passed(round_num, review, audit)
        for l in lines:
            print(l)
        return lines

    def on_failed(self, round_num: int, max_rounds: int,
                   review: ReviewOutput, audit: AuditOutput) -> list[str]:
        fails = [s for s, r in [("review", review.result), ("audit", audit.result)] if r != "PASS"]
        lines = [f"\n{_bold('=' * 46)}",
                 f"  {_red('❌')} Round {round_num} 失败 — {_red('，'.join(fails))}"]
        if review.issues:
            lines.append(f"\n  ── Review Issues ({len(review.issues)}) ──")
            for i in review.issues:
                lines.append(f"    [{i.severity.upper()}] {i.file}: {i.description}")
        if audit.vulnerabilities:
            lines.append(f"\n  ── Audit Issues ({len(audit.vulnerabilities)}) ──")
            for v in audit.vulnerabilities:
                lines.append(f"    [{v.severity.upper()}] {v.file}: {v.description}")
        if round_num < max_rounds:
            lines.append(f"\n  → 进入 Round {round_num + 1}/{max_rounds}")
        else:
            lines.append(f"\n  → 已达最大轮数")
        lines.append(f"{'=' * 46}")
        for l in lines:
            print(l)
        return lines

    def on_exhausted(self, round_num: int, max_rounds: int,
                      last_review: ReviewOutput, last_audit: AuditOutput,
                      fail_report: str) -> list[str]:
        print(f"\n{'=' * 46}")
        print(f"  ⛔ Quad-Core Flow exhausted — max rounds ({max_rounds}) reached")
        print(f"  Last review: {last_review.result}")
        print(f"  Last audit: {last_audit.result}")
        print(f"{'=' * 46}")
        return [f"\nMax rounds ({max_rounds}) reached — fail_report: {fail_report}"]

    def on_error(self, msg: str) -> list[str]:
        print(f"  Error: {msg}")
        return [f"Error: {msg}"]


# ══════════════════════════════════════════════════════════════
# QCFEngine
# ══════════════════════════════════════════════════════════════

class QCFEngine:
    """State machine that orchestrates implement → review → audit rounds."""

    def __init__(self, config: Config,
                 reporter: ProgressReporter | None = None,
                 hooks: Hooks | None = None) -> None:
        self.config = config
        self.reporter = reporter or StdoutReporter()
        self.hooks = hooks or config.build_hooks()
        self.overview = RoundsOverview()
        self._consecutive_fails = 0
        self._no_commit = False

    async def run(
        self,
        design_doc: Path,
        max_rounds: int | None = None,
        start_stage: str = "implement",
        no_commit: bool = False,
    ) -> str:
        """Execute the QCF inner loop (implement → review → audit).

        Returns:
            ``"PASS"`` — all checks passed (commit made).
            ``"FAIL"`` — max rounds exhausted.
            ``"REPLAN"`` — evolution sandbox triggered.
        """
        cfg = self.config
        design_doc = Path(design_doc)
        self._no_commit = no_commit
        self._consecutive_fails = 0

        if not design_doc.exists():
            print(f"Error: {design_doc} not found")
            return "FAIL"

        design_content = design_doc.read_text()  # kept for replan context

        # MEDIUM-2: Restrict permissions on all files created by this process
        # and its subprocesses (including /tmp review/audit issue files).
        os.umask(0o077)
        max_rounds = max_rounds or cfg.max_rounds

        # Initialize AgentProgress dashboard
        progress = AgentProgress(
            target=design_doc.stem.replace("-design", ""),
            max_rounds=max_rounds,
        )

        # Initial status
        _write_status(cfg.status_file, {
            "design_doc": str(design_doc),
            "started_at": _now(),
            "max_rounds": max_rounds,
            "current_round": 1,
            "current_stage": "starting",
            "history": [],
            "final_result": None,
        })

        self.reporter.on_start(design_doc, max_rounds)
        await self.hooks.run_async("post-start",
            design_doc=str(design_doc), max_rounds=max_rounds, round=1)

        round_num = 1
        last_review = ReviewOutput(result="N/A", summary="")
        last_audit = AuditOutput(result="N/A", summary="")
        fail_reports: list[str] = []

        while round_num <= max_rounds:
            # Clean previous issue files
            for f in (cfg.issues_file, cfg.review_issues_file, cfg.audit_issues_file):
                f.unlink(missing_ok=True)

            # ── Stage 1: Implement or Fix ──
            if round_num == 1 and start_stage == "implement":
                stage_name = "implement"
                await self.hooks.run_async("pre-stage", stage=stage_name, round=round_num)
                self.reporter.on_stage_start(round_num, max_rounds, stage_name)
                progress.update_before_round(stage_name, round_num)
                result_text, metrics = await _run_implement(cfg, design_doc, round_num)
            else:
                stage_name = "fix"
                await self.hooks.run_async("pre-stage", stage=stage_name, round=round_num)
                self.reporter.on_stage_start(round_num, max_rounds, stage_name)
                progress.update_before_round(stage_name, round_num)
                result_text, metrics = await _run_fix(cfg, design_doc, round_num)

            stage_result = "TIMEOUT" if metrics.timed_out else "PASS"
            self.overview.add(RoundStageMetric(
                stage=stage_name, result=stage_result,
                input_tokens=metrics.input_tokens, output_tokens=metrics.output_tokens,
            ))
            self.reporter.on_stage_end(round_num, stage_name, metrics)
            progress.update_on_complete({
                "stage": stage_name, "round": round_num,
                "status": stage_result,
                "next_action": "review + audit" if not metrics.timed_out else f"round {round_num + 1}",
            })
            print(f"[QCF] stage: {stage_name} → {stage_result}")
            await self.hooks.run_async("post-stage",
                stage=stage_name, round=round_num,
                result="TIMEOUT" if metrics.timed_out else "PASS",
                input_tokens=metrics.input_tokens, output_tokens=metrics.output_tokens,
                timed_out=metrics.timed_out)

            if metrics.timed_out:
                self._consecutive_fails += 1
                self.overview.add(RoundStageMetric(stage="review", result="SKIP",
                                                   summary="[implement/fix timed out]"))
                self.overview.add(RoundStageMetric(stage="audit", result="SKIP",
                                                   summary="[implement/fix timed out]"))
                progress.update_on_complete({
                    "stage": stage_name, "round": round_num,
                    "status": "TIMEOUT",
                    "failed_stages": [stage_name],
                    "next_action": f"round {round_num + 1}",
                })

                # Check consecutive fails for REPLAN
                if self._consecutive_fails >= cfg.max_consecutive_fails:
                    print(f"\n  ⛔ REPLAN triggered — {self._consecutive_fails} consecutive failures")
                    _write_status(cfg.status_file, {"current_stage": "replan"})
                    progress.update_on_complete({
                        "stage": "replan", "round": round_num,
                        "status": "REPLAN",
                        "action_suggestion": "REPLAN",
                        "next_action": "evolution sandbox",
                    })
                    await self._handle_replan(cfg, fail_reports, design_content)
                    return "REPLAN"

                print(f"\n  → 结果: implement/fix {_red('TIMEOUT')} → 进入 Round {round_num + 1}/{max_rounds}")
                round_num += 1
                continue

            # ── Stage 2: Review + Audit (parallel) ──
            self.reporter.on_stage_start(round_num, max_rounds, "review")
            await self.hooks.run_async("pre-stage", stage="review+audit", round=round_num)
            progress.update_before_round("review+audit", round_num)
            _write_status(cfg.status_file, {
                "current_round": round_num,
                "current_stage": "reviewing + auditing",
                "history": [m.__dict__ for m in self.overview.entries],
                "final_result": None,
            })

            review_task = _run_review(cfg, design_doc, round_num)
            audit_task = _run_audit(cfg, design_doc, round_num)
            review, audit = await asyncio.gather(review_task, audit_task)

            last_review, last_audit = review, audit

            print(f"[QCF] stage: review → {review.result}")
            print(f"[QCF] stage: audit → {audit.result}")
            print(f"[QCF] action_suggestion → {audit.action_suggestion}")

            self.overview.add(RoundStageMetric(
                stage="review", result=review.result, summary=review.summary,
            ))
            self.overview.add(RoundStageMetric(
                stage="audit", result=audit.result, summary=audit.summary,
            ))

            _write_status(cfg.status_file, {
                "current_round": round_num,
                "current_stage": f"review ({review.result}) + audit ({audit.result})",
                "history": [m.__dict__ for m in self.overview.entries],
                "final_result": None,
            })

            self.reporter.on_round_result(round_num, max_rounds, review, audit)
            await self.hooks.run_async("post-round",
                round=round_num, max_rounds=max_rounds,
                review_result=review.result, audit_result=audit.result,
                review_summary=review.summary, audit_summary=audit.summary)

            # Merge issues for next round's fix
            all_issues: list[Issue] = []
            all_issues.extend(review.issues)
            all_issues.extend(audit.vulnerabilities)
            if all_issues:
                cfg.issues_file.write_text("\n".join(i.to_line() for i in all_issues))
                os.chmod(cfg.issues_file, 0o600)

            # ── Print round summary ──
            self.overview.print_round_summary(round_num, max_rounds)

            # ── Decision ──
            if review.result == "PASS" and audit.result == "PASS":
                self._consecutive_fails = 0
                print(f"[QCF] round {round_num} → PASS")
                self.reporter.on_passed(round_num, review, audit)
                await self.hooks.run_async("on-passed",
                    round=round_num,
                    review_result=review.result, audit_result=audit.result,
                    review_summary=review.summary, audit_summary=audit.summary)

                progress.update_on_complete({
                    "stage": "round", "round": round_num,
                    "status": "PASS", "task": f"round-{round_num:02d} all checks passed",
                    "next_action": "completed",
                })

                _save_final_reports(cfg, round_num, "PASS")
                if not self._no_commit:
                    _auto_commit(cfg, round_num, stage_name)

                self.overview.print_final_summary()
                _write_status(cfg.status_file, {
                    "current_round": round_num,
                    "current_stage": "completed",
                    "history": [m.__dict__ for m in self.overview.entries],
                    "final_result": "PASS — all checks passed",
                    "result_analysis": f"review: {review.summary}\naudit: {audit.summary}",
                })
                return "PASS"

            # FAIL → next round
            self._consecutive_fails += 1
            print(f"[QCF] round {round_num} → FAIL (consecutive fails: {self._consecutive_fails})")
            self.reporter.on_failed(round_num, max_rounds, review, audit)

            progress.update_on_complete({
                "stage": "round", "round": round_num,
                "status": "FAIL",
                "failed_stages": [s for s, r in [("review", review.result), ("audit", audit.result)] if r != "PASS"],
                "action_suggestion": audit.action_suggestion,
                "next_action": "evolution sandbox" if (
                    audit.action_suggestion == "REPLAN" or self._consecutive_fails >= cfg.max_consecutive_fails
                ) else f"round {round_num + 1}",
            })

            # Check for REPLAN
            if audit.action_suggestion == "REPLAN" or self._consecutive_fails >= cfg.max_consecutive_fails:
                print(f"\n  ⛔ REPLAN triggered — escalation to evolution sandbox")
                print(f"    action_suggestion={audit.action_suggestion}, consecutive_fails={self._consecutive_fails}")
                _write_status(cfg.status_file, {"current_stage": "replan"})
                # Write fail report before escalation (design requires escalation report)
                report_text = _write_fail_report(cfg, round_num, review, audit)
                fail_reports.append(report_text)
                await self._handle_replan(cfg, fail_reports, design_content)
                return "REPLAN"

            fails = [s for s, r in [("review", review.result), ("audit", audit.result)] if r != "PASS"]
            await self.hooks.run_async("on-failed",
                round=round_num, max_rounds=max_rounds,
                failed_stages=",".join(fails),
                review_result=review.result, audit_result=audit.result,
                review_summary=review.summary, audit_summary=audit.summary)

            # Build fail report for evolution context
            report_text = _write_fail_report(cfg, round_num, review, audit)
            fail_reports.append(report_text)

            round_num += 1

        # ── Max rounds exhausted ──
        _save_final_reports(cfg, max_rounds, "FAIL")
        report_text = _write_fail_report(cfg, max_rounds, last_review, last_audit)
        fail_reports.append(report_text)
        self.reporter.on_exhausted(round_num, max_rounds, last_review, last_audit, report_text)
        await self.hooks.run_async("on-exhausted",
            round=max_rounds, max_rounds=max_rounds,
            review_result=last_review.result, audit_result=last_audit.result,
            fail_report=report_text)

        progress.update_on_complete({
            "stage": "exhausted", "round": max_rounds,
            "status": "FAIL",
            "next_action": "manual review required",
        })

        self.overview.print_final_summary()
        _write_status(cfg.status_file, {
            "current_round": max_rounds,
            "current_stage": "failed",
            "history": [m.__dict__ for m in self.overview.entries],
            "final_result": f"FAIL — max rounds ({max_rounds}) reached. "
                           f"review: {last_review.result}, audit: {last_audit.result}",
            "fail_analysis": report_text,
        })
        return "FAIL"

    async def _handle_replan(
        self,
        cfg: Config,
        fail_reports: list[str],
        design_content: str,
    ) -> None:
        """Handle REPLAN trigger — escalate to evolution sandbox."""
        print(f"\n{'=' * 50}")
        print(f"  ⛔ REPLAN — Escalating to Evolution Sandbox")
        print(f"{'=' * 50}")

        if not cfg.evolution_enabled:
            print("  Evolution disabled by config — skipping sandbox.")
            return

        from . import evolver
        try:
            success = await evolver.run_evolution(cfg, fail_reports, design_content)
            if success:
                print("  ✅ Evolution completed and merged.")
            else:
                print("  ❌ Evolution failed — see rejection report.")
        except Exception as e:
            print(f"  Evolution error: {e}")

    async def run_continuous(self, task_path: Path, max_iterations: int = 10) -> None:
        """Outer loop: Tech-Lead → inner loop → Pilot → repeat until steady state."""
        cfg = self.config
        print(f"\n{_bold('=' * 50)}")
        print(f"  {_bold('⚡ The Quad-Core Flow — Continuous Mode')}")
        print(f"  Starting task: {task_path.name}")
        print(f"{_bold('=' * 50)}\n")

        _write_status(cfg.status_file, {
            "continuous": True,
            "task": str(task_path),
            "started_at": _now(),
            "iteration": 1,
            "current_stage": "tech-lead",
            "history": [],
            "final_result": None,
        })

        current_task = task_path
        iteration = 1
        summary_content = ""  # Loaded from summary pack between iterations

        while iteration <= max_iterations:
            print(f"\n╔═══ Iteration {iteration} ═══╗")

            # ── Step 1: Tech-Lead (generate design doc) ──
            print(f"\n  [Core 1] Tech-Lead — analyzing project...")
            design_doc = await _run_tech_lead(cfg, current_task, summary_pack=summary_content)
            if design_doc is None:
                print("  Tech-Lead failed — aborting continuous loop.")
                break

            # ── Step 2: Inner loop (implement → review → audit) ──
            print(f"\n  [Core 2-4] Starting inner loop...")
            result = await self.run(design_doc)

            # Handle REPLAN from inner loop
            if result == "REPLAN":
                print(f"\n  [QCF] Inner loop returned REPLAN — evolution sandbox initiated.")
                _write_status(cfg.status_file, {
                    "current_stage": "replan",
                    "final_result": "REPLAN — evolution triggered",
                })
                break

            # Build round history for pilot
            round_history = [
                f"{m.stage}: {m.result}" + (f" ({m.summary[:60]})" if m.summary else "")
                for m in self.overview.entries
            ]

            # ── Step 3: Pilot — decide next action ──
            print(f"\n  [Core 5] Pilot — assessing project state...")
            verdict, project_summary = await _run_pilot(
                cfg,
                last_task=current_task.name,
                round_history=round_history,
            )

            if verdict == "STEADY_STATE":
                print(f"[QCF] pipeline → PASS")
                print(f"\n{_bold('=' * 50)}")
                print(f"  {_green('✅')} {_bold(f'Quad-Core Flow reached STEADY STATE after {iteration} iteration(s)')}")
                print(f"{_bold('=' * 50)}")
                _write_status(cfg.status_file, {
                    "current_stage": "steady_state",
                    "iteration": iteration,
                    "final_result": "STEADY_STATE — all tasks complete",
                })
                break

            # New task generated by Pilot — produce summary pack for next iteration
            current_task = Path(verdict)
            if not current_task.exists():
                print(f"  Pilot task file not found: {current_task}")
                break

            # Use Pilot's PROJECT_SUMMARY if available, else fall back to code analysis
            if project_summary:
                summary_content = project_summary
                print(f"  Project summary extracted from Pilot")
            else:
                summary_content = _write_summary_pack(cfg, current_task, round_history)
            if summary_content:
                print(f"  Summary pack written to {cfg.summary_pack_file}")

            print(f"\n  → New task discovered: {current_task.name}")
            _write_status(cfg.status_file, {
                "current_stage": f"pilot → new task: {current_task.name}",
                "iteration": iteration + 1,
            })

            # Reset overview for next iteration
            self.overview = RoundsOverview()
            iteration += 1

        else:
            print(f"[QCF] pipeline → FAIL (max iterations)")
            print(f"\n{_bold('=' * 50)}")
            print(f"  {_red('⛔')} {_bold(f'Max iterations ({max_iterations}) reached — continuous loop stopped')}")
            print(f"{_bold('=' * 50)}")
