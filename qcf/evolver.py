"""Evolver + Meta-Audit orchestration for self-evolving pipeline.

Handles the full evolution cycle:
  1. Create worktree sandbox
  2. Run Evolver agent (analyze + modify)
  3. Run Meta-Audit agent (validate)
  4. Merge back on PASS or log rejection on FAIL
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .runner import run_claude
from . import prompts
from . import worktree as wt

logger = logging.getLogger(__name__)

_EVOLVE_REPORT_DIR = Path("output/docs/qcf")


async def run_evolution(
    cfg: Config,
    fail_logs: list[str],
    current_design: str,
) -> bool:
    """Orchestrate the full evolution cycle.

    Args:
        cfg: Pipeline configuration.
        fail_logs: List of fail report texts from recent rounds.
        current_design: Current design document content.

    Returns:
        True if evolution succeeded and changes were merged,
        False otherwise.
    """
    print(f"\n{'=' * 50}")
    print(f"  ⚡ Evolution Sandbox — Starting")
    print(f"{'=' * 50}\n")

    # ── Step 1: Create worktree ──
    branch = wt.get_evolve_branch_name()
    worktree_path = wt.create_evolve_worktree(cfg.root_dir, branch)

    if worktree_path is None:
        print("  ⚠ Worktree creation failed — running evolution in-place")
        # Fallback: operate in current repo
        worktree_path = cfg.root_dir

    in_place = worktree_path == cfg.root_dir

    try:
        # ── Step 2: Collect failure context ──
        context = _collect_failure_context(cfg, fail_logs, current_design)

        # ── Step 3: Run Evolver agent ──
        print("  [Evolver] Analyzing failure patterns and modifying code...")
        evolver_ok = await _run_evolver_agent(cfg, context, worktree_path)
        if not evolver_ok:
            print("  [Evolver] Failed — aborting evolution")
            return False

        # ── Step 4: Commit Evolver changes in worktree so merge can find them ──
        if not in_place:
            _commit_worktree_changes(worktree_path, branch)
        else:
            _commit_in_place(cfg, branch)

        # ── Step 5: Get diff for Meta-Audit ──
        if not in_place:
            diff = wt.diff_between("HEAD", branch, cfg.root_dir)
        else:
            # In-place: use working tree diff
            import subprocess
            try:
                result = subprocess.run(
                    ["git", "diff", "HEAD", "--", "qcf/"],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(cfg.root_dir),
                )
                diff = result.stdout
            except (OSError, subprocess.TimeoutError):
                diff = "(unable to get diff)"

        if not diff.strip():
            print("  [Evolver] No changes detected — nothing to audit")
            return True

        # ── Step 5: Run Meta-Audit ──
        print("  [Meta-Audit] Validating changes...")
        meta_audit_result = await _run_meta_audit(
            cfg, current_design, diff, fail_logs,
        )

        if meta_audit_result == "PASS":
            print(f"\n  ✅ Meta-Audit: PASS — changes approved")
            if not in_place:
                _merge_worktree(cfg.root_dir, branch, worktree_path)
            else:
                _commit_in_place(cfg, branch)
            print("  Evolution completed successfully.")
            return True
        else:
            print(f"\n  ❌ Meta-Audit: FAIL — changes rejected")
            _save_rejection_report(cfg, diff, meta_audit_result)
            if not in_place:
                print(f"  Worktree preserved for inspection: {worktree_path}")
            return False

    except Exception as e:
        logger.exception("Evolution failed with exception")
        print(f"  Evolution error: {e}")
        return False


async def _run_evolver_agent(
    cfg: Config,
    context: dict[str, Any],
    worktree_path: Path,
) -> bool:
    """Run the Evolver agent to analyze and fix pipeline code.

    The Evolver agent receives failure context and modifies QCF scripts/prompts
    in the worktree to address root causes.
    """
    prompt_text = prompts.evolver_prompt(
        fail_logs=context.get("fail_logs", []),
        current_design=context.get("current_design", ""),
        project_tree=context.get("project_tree", ""),
        audit_history=context.get("audit_history", ""),
        worktree_path=str(worktree_path),
    )
    log_path = cfg.log_dir / "qcf-evolver.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.evolve_timeout,
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        cwd=worktree_path,
    )

    if metrics.timed_out:
        print("  [Evolver] TIMEOUT")
        return False

    print(f"  [Evolver] done — {metrics.input_tokens} in / {metrics.output_tokens} out")
    return True


def _commit_worktree_changes(worktree_path: Path, branch: str) -> bool:
    """Commit Evolver modifications in the worktree so they appear on *branch*."""
    import subprocess

    try:
        ret = subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, timeout=15,
            cwd=str(worktree_path),
        )
        if ret.returncode != 0:
            return False

        ret = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True, timeout=15,
            cwd=str(worktree_path),
        )
        if ret.returncode == 0:
            return True  # Nothing to commit — still ok

        ret = subprocess.run(
            ["git", "commit", "-m",
             f"feat(qcf): evolution changes on {branch}"
             f"\n\nCo-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"],
            capture_output=True, timeout=30,
            cwd=str(worktree_path),
        )
        return ret.returncode == 0
    except OSError:
        return False


async def _run_meta_audit(
    cfg: Config,
    current_design: str,
    diff: str,
    fail_logs: list[str],
) -> str:
    """Run the Meta-Audit agent to validate Evolver changes.

    Returns:
        ``"PASS"`` or ``"FAIL"``
    """
    prompt_text = prompts.meta_audit_prompt(
        current_design=current_design,
        diff=diff,
        fail_logs="\n---\n".join(fail_logs[-3:]),  # Last 3 fail logs
    )
    log_path = cfg.log_dir / "qcf-meta-audit.log"
    result_text, metrics = await run_claude(
        prompt_text, log_path,
        timeout=cfg.meta_audit_timeout,
        allowed_tools=cfg.allowed_tools,
        output_format=cfg.output_format,
        cwd=cfg.root_dir,
    )

    if metrics.timed_out:
        print("  [Meta-Audit] TIMEOUT — treating as FAIL")
        return "FAIL"

    # Parse result
    import re
    m = re.search(r"META_AUDIT_RESULT\s*:\s*(PASS|FAIL)", result_text, re.IGNORECASE)
    result = m.group(1).upper() if m else "FAIL"

    print(f"  [Meta-Audit] {result} — {metrics.input_tokens} in / {metrics.output_tokens} out")
    return result


def _find_latest_audit_log(cfg: Config) -> Path | None:
    """Find the most recent audit log by scanning for ``qcf-audit-*.log`` files."""
    import glob
    pattern = str(cfg.log_dir / "qcf-audit-*.log")
    logs = sorted(glob.glob(pattern))
    return Path(logs[-1]) if logs else None


def _collect_failure_context(
    cfg: Config,
    fail_logs: list[str],
    current_design: str,
) -> dict[str, Any]:
    """Gather failure context for the Evolver agent."""
    # Read audit history from the latest audit log
    audit_history = ""
    latest_audit_log = _find_latest_audit_log(cfg)
    if latest_audit_log and latest_audit_log.exists():
        audit_history = latest_audit_log.read_text("utf-8", errors="replace")[:5000]

    # Project tree
    tree = prompts.project_tree(cwd=cfg.root_dir, max_depth=4)

    return {
        "fail_logs": fail_logs,
        "current_design": current_design,
        "project_tree": tree,
        "audit_history": audit_history,
    }


def _merge_worktree(repo_path: Path, branch: str, worktree_path: Path) -> None:
    """Merge the evolution branch and clean up the worktree."""
    import subprocess

    # Checkout the branch's changes into main
    try:
        # Squash-merge the evolve branch
        result = subprocess.run(
            ["git", "merge", "--squash", branch],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_path),
        )
        if result.returncode == 0:
            subprocess.run(
                ["git", "commit", "-m", f"feat(qcf): evolution merge from {branch}"
                 f"\n\nCo-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"],
                capture_output=True, timeout=30,
                cwd=str(repo_path),
            )
    except OSError as e:
        logger.error("Merge failed: %s", e)

    # Remove worktree
    wt.remove_worktree(worktree_path)


def _commit_in_place(cfg: Config, branch: str) -> None:
    """Commit evolution changes when running in-place."""
    import subprocess

    ret = subprocess.run(["git", "add", "-u"], capture_output=True, timeout=15,
                         cwd=str(cfg.root_dir))
    if ret.returncode != 0:
        return

    ret = subprocess.run(["git", "diff", "--cached", "--quiet"],
                         capture_output=True, timeout=15, cwd=str(cfg.root_dir))
    if ret.returncode == 0:
        return  # Nothing to commit

    subprocess.run(
        ["git", "commit", "-m",
         f"feat(qcf): in-place evolution ({branch})"
         f"\n\nCo-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"],
        capture_output=True, timeout=30,
        cwd=str(cfg.root_dir),
    )


def _save_rejection_report(cfg: Config, diff: str, meta_audit_result: str) -> None:
    """Save a detailed rejection report when Meta-Audit fails."""
    report_dir = cfg.docs_dir / _EVOLVE_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    report_path = report_dir / f"evolution-rejected-{time.strftime('%Y%m%d-%H%M%S')}.md"
    report_content = (
        f"# Evolution Rejected\n\n"
        f"- **Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **Meta-Audit Result**: {meta_audit_result}\n\n"
        f"## Diff\n\n```diff\n{diff}\n```\n"
    )
    report_path.write_text(report_content)
    os.chmod(report_path, 0o600)
    print(f"  Rejection report: {report_path}")
