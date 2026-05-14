"""Git worktree sandbox for self-evolution.

Provides utilities to create, manage, and clean up git worktrees
used by the Evolver agent for safe pipeline code modification.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_evolve_branch_name() -> str:
    """Generate a unique branch name for an evolution attempt.

    Returns:
        ``evolve/YYYYMMDD-HHMMSS``
    """
    return f"evolve/{time.strftime('%Y%m%d-%H%M%S')}"


def create_evolve_worktree(
    repo_path: Path,
    branch_name: Optional[str] = None,
) -> Optional[Path]:
    """Create a git worktree for safe evolution experimentation.

    Uses ``git worktree add`` to create a separate working directory
    from the current HEAD. Falls back to in-place mode if git worktree
    is unavailable or the repo is dirty.

    Args:
        repo_path: Root of the git repository.
        branch_name: Name for the evolution branch (auto-generated if None).

    Returns:
        Path to the worktree directory, or ``None`` if creation failed
        (fallback to in-place mode).
    """
    branch = branch_name or get_evolve_branch_name()
    worktree_dir = repo_path.parent / f"evolve_{branch.replace('/', '-')}"

    if worktree_dir.exists():
        logger.warning("Worktree path already exists: %s", worktree_dir)
        # Use timestamp suffix
        suffix = time.strftime("-%H%M%S")
        worktree_dir = repo_path.parent / f"evolve_{branch.replace('/', '-')}{suffix}"

    # Check if git worktree is available
    try:
        subprocess.run(
            ["git", "worktree", "help"],
            capture_output=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutError):
        logger.warning("git worktree not available — falling back to in-place mode")
        return None

    # Auto-stash if the repo is dirty
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    )
    if status.stdout.strip():
        logger.info("Dirty working tree — stashing before worktree creation")
        subprocess.run(["git", "stash", "push", "-m", "qcf-evolve-auto-stash"],
                       capture_output=True, timeout=30)

    try:
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_dir), "HEAD"],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            logger.warning(
                "git worktree add failed (%s): %s — falling back to in-place mode",
                result.returncode, result.stderr.strip(),
            )
            return None
    except (OSError, subprocess.TimeoutError) as e:
        logger.warning("git worktree add error: %s — falling back to in-place mode", e)
        return None

    return worktree_dir.resolve()


def remove_worktree(worktree_path: Path) -> bool:
    """Remove a git worktree and its associated branch.

    Args:
        worktree_path: Path to the worktree directory.

    Returns:
        True if removal was successful, False otherwise.
    """
    if not worktree_path.exists():
        return True

    resolved = worktree_path.resolve()

    try:
        # Find the branch associated with this worktree
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=15,
        )
        branch = None
        current_path = None
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                current_path = line[9:].strip()
            elif line.startswith("branch ") and current_path == str(resolved):
                branch = line[7:].strip()
                break

        # Direct removal
        result = subprocess.run(
            ["git", "worktree", "remove", str(worktree_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error("Failed to remove worktree: %s", result.stderr.strip())
                return False

        # Delete only the associated branch, not all evolve/* branches
        if branch:
            branch_short = branch.removeprefix("refs/heads/")
            subprocess.run(
                ["git", "branch", "-D", branch_short],
                capture_output=True, timeout=15,
            )

        return True
    except (OSError, subprocess.TimeoutError) as e:
        logger.error("Error removing worktree: %s", e)
        return False


def run_in_worktree(
    worktree_path: Path,
    cmd: list[str],
    timeout: int = 300,
) -> tuple[str, int]:
    """Run a command in the worktree context.

    Args:
        worktree_path: Worktree directory.
        cmd: Command list to execute.
        timeout: Timeout in seconds.

    Returns:
        ``(stdout, returncode)``
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout,
            cwd=str(worktree_path),
        )
        return result.stdout, result.returncode
    except subprocess.TimeoutError:
        return "(TIMEOUT)", -1
    except OSError as e:
        return f"(error: {e})", -1


def diff_between(branch_a: str, branch_b: str, repo_path: Path) -> str:
    """Get the diff between two branches in the repository.

    Args:
        branch_a: Base branch.
        branch_b: Comparison branch.
        repo_path: Repository root.

    Returns:
        Unified diff as a string.
    """
    try:
        result = subprocess.run(
            ["git", "diff", branch_a, branch_b, "--", "qcf/"],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo_path),
        )
        return result.stdout
    except (OSError, subprocess.TimeoutError) as e:
        return f"(error getting diff: {e})"


def list_worktrees() -> list[dict[str, str]]:
    """List active git worktrees.

    Returns:
        List of dicts with ``path``, ``branch``, ``bare`` keys.
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=15,
        )
        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.split("\n"):
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line[9:].strip()}
            elif line.startswith("branch ") and current is not None:
                current["branch"] = line[7:].strip()
            elif line.startswith("bare"):
                if current is not None:
                    current["bare"] = "true"
        if current:
            worktrees.append(current)
        return worktrees
    except (OSError, subprocess.TimeoutError) as e:
        logger.error("Error listing worktrees: %s", e)
        return []
