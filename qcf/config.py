"""Configuration loading from qcf.toml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .hooks import Hooks

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "default_config.toml"


def _load_default_toml() -> dict[str, Any]:
    with open(_DEFAULT_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


@dataclass
class Config:
    """Pipeline configuration — fields are all public and user-facing."""

    # ── Project root (where qcf.toml lives, or CWD) ──
    root_dir: Path = field(default_factory=Path.cwd)

    # ── Workspace ──
    docs_dir: Path = Path("output/docs")
    status_file: Path = Path("/tmp/qcf-status.json")
    log_dir: Path = Path("/tmp")

    # ── Paths (resolved relative to docs_dir) ──
    tech_lead_dir: Path = Path("output/docs/tech-lead")
    code_reviewer_dir: Path = Path("output/docs/code-reviewer")
    security_reviewer_dir: Path = Path("output/docs/security-reviewer")
    coder_dir: Path = Path("output/docs/coder")
    out_review_dir: Path = Path("output/docs/code-reviewer")
    out_audit_dir: Path = Path("output/docs/security-reviewer")
    fail_dir: Path = Path("output/docs/qcf")

    # ── Task dir (high-level task descriptions for Core 1 Tech-Lead) ──
    task_dir: Path = Path("tasks")

    # ── Runtime files ──
    issues_file: Path = Path("/tmp/qcf-issues-latest.txt")
    review_issues_file: Path = Path("/tmp/qcf-review-issues.txt")
    audit_issues_file: Path = Path("/tmp/qcf-audit-issues.txt")
    pilot_task_file: Path = Path("/tmp/qcf-pilot-task.txt")

    # ── Stage timeouts (seconds) ──
    max_rounds: int = 3
    tech_lead_timeout: int = 300
    implement_timeout: int = 600
    fix_timeout: int = 600
    review_timeout: int = 300
    audit_timeout: int = 300
    pilot_timeout: int = 120

    # ── Claude model overrides (empty = default) ──
    review_model: str = "sonnet"
    audit_model: str = ""

    # ── Token budget ──
    max_output_tokens: int = 8192
    thinking_budget: int | None = None

    # ── Claude CLI flags ──
    allowed_tools: list[str] = field(default_factory=lambda: ["Write", "Read", "Edit", "Bash"])
    output_format: str = "json"

    # ── Commit behavior ──
    commit_enabled: bool = True
    commit_message_template: str = "feat(qcf): round-{round_num:02d} all checks passed"
    commit_message_stage_template: str = "feat(qcf): [{stage}] round-{round_num:02d} checks passed"
    co_author: str = "Claude Opus 4.7 <noreply@anthropic.com>"

    # ── Summary pack ──
    summary_pack_file: Path = Path("/tmp/qcf-summary-pack.json")

    # ── Evolution / Self-Improvement ──
    evolution_enabled: bool = True
    worktree_base: Path = Path("../evolve")
    evolve_timeout: int = 600
    meta_audit_timeout: int = 300
    max_consecutive_fails: int = 3

    # ── Hooks ──
    hooks_dir: Path | None = None
    hooks_commands: dict[str, list[str]] = field(default_factory=dict)

    # ── Internal ──
    _config_path: Path | None = None

    # ── Public helpers ──

    def timeout_for(self, stage: str) -> int:
        return {
            "tech-lead": self.tech_lead_timeout,
            "implement": self.implement_timeout,
            "fix": self.fix_timeout,
            "review": self.review_timeout,
            "audit": self.audit_timeout,
            "pilot": self.pilot_timeout,
        }.get(stage, 600)

    def model_for(self, stage: str) -> str | None:
        return {
            "review": self.review_model,
            "audit": self.audit_model,
        }.get(stage) or None

    def commit_message(self, round_num: int) -> str:
        msg = self.commit_message_template.format(round_num=round_num)
        if self.co_author:
            msg += f"\n\nCo-Authored-By: {self.co_author}"
        return msg

    def commit_message_stage(self, stage: str, round_num: int) -> str:
        msg = self.commit_message_stage_template.format(stage=stage, round_num=round_num)
        if self.co_author:
            msg += f"\n\nCo-Authored-By: {self.co_author}"
        return msg

    def build_hooks(self) -> Hooks:
        """Create a ``Hooks`` instance from this config."""
        from .hooks import Hooks  # late import to avoid circular

        hooks_dir = self.hooks_dir
        # Auto-discover .qcf-hooks/ if not explicitly configured
        if hooks_dir is None:
            candidate = self.root_dir / ".qcf-hooks"
            if candidate.is_dir():
                hooks_dir = candidate
        h = Hooks(hooks_dir=hooks_dir)
        h.add_commands(self.hooks_commands)
        return h

    def to_status_dict(self) -> dict[str, Any]:
        import time
        return {
            "root_dir": str(self.root_dir),
            "docs_dir": str(self.docs_dir),
            "max_rounds": self.max_rounds,
            "config_file": str(self._config_path) if self._config_path else "(defaults)",
            "_captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ── Factory ──

    @classmethod
    def load(cls, path: str | Path | None = None, *, cwd: Path | None = None) -> "Config":
        """Load config from a qcf.toml, merging with defaults.

        Resolution order:
          1. Explicit *path* (if given)
          2. ``{cwd}/qcf.toml`` (if exists)
          3. ``{cwd}/.qcf.toml`` (if exists)
          4. In-package defaults
        """
        cfg = cls()
        cwd = cwd or Path.cwd()

        # Locate config file
        cfg_path: Path | None = None
        if path is not None:
            cfg_path = Path(path)
        else:
            for candidate in (cwd / "qcf.toml", cwd / ".qcf.toml"):
                if candidate.exists():
                    cfg_path = candidate
                    break

        if cfg_path is None or not cfg_path.exists():
            cfg.root_dir = cwd
            # Still resolve relative paths to CWD
            cfg._resolve_paths(cwd)
            return cfg

        cfg._config_path = cfg_path.resolve()
        cfg.root_dir = cfg_path.parent.resolve()

        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)

        ws = data.get("workspace", {})

        # workspace.root — overrides where relative paths anchor
        if "root" in ws:
            r = Path(ws["root"])
            cfg.root_dir = r if r.is_absolute() else cfg.root_dir / r

        # docs_dir
        if "docs_dir" in ws:
            d = Path(ws["docs_dir"])
            cfg.docs_dir = d if d.is_absolute() else cfg.root_dir / d

        # status_file / log_dir
        for key, attr in (("status_file", "status_file"), ("log_dir", "log_dir")):
            if key in ws:
                setattr(cfg, attr, Path(ws[key]))

        # Paths (resolved relative to docs_dir)
        paths = data.get("paths", {})
        mapping = {
            "tech_lead": "tech_lead_dir",
            "code_reviewer": "code_reviewer_dir",
            "security_reviewer": "security_reviewer_dir",
            "coder": "coder_dir",
            "out_review": "out_review_dir",
            "out_audit": "out_audit_dir",
            "fail": "fail_dir",
            "task": "task_dir",
        }
        for key, attr in mapping.items():
            if key in paths:
                p = Path(paths[key])
                setattr(cfg, attr, p if p.is_absolute() else cfg.docs_dir / p)

        # Files
        files = data.get("files", {})
        for key, attr in (("issues", "issues_file"), ("review_issues", "review_issues_file"),
                          ("audit_issues", "audit_issues_file")):
            if key in files:
                setattr(cfg, attr, Path(files[key]))

        # Stages
        stages = data.get("stages", {})
        for key in ("max_rounds", "tech_lead_timeout", "implement_timeout",
                     "fix_timeout", "review_timeout", "audit_timeout", "pilot_timeout"):
            if key in stages:
                setattr(cfg, key, stages[key])

        # Models
        models = data.get("models", {})
        if "review" in models:
            cfg.review_model = models["review"]
        if "audit" in models:
            cfg.audit_model = models["audit"]

        # Commit
        commit = data.get("commit", {})
        for key in ("enabled",):
            if key in commit:
                setattr(cfg, f"commit_{key}", commit[key])
        for key in ("message_template", "co_author"):
            if key in commit:
                setattr(cfg, f"commit_{key}", commit[key])

        # Claude CLI
        claude = data.get("claude", {})
        if "allowed_tools" in claude:
            cfg.allowed_tools = claude["allowed_tools"]
        if "output_format" in claude:
            cfg.output_format = claude["output_format"]
        if "max_output_tokens" in claude:
            cfg.max_output_tokens = int(claude["max_output_tokens"])
        if "thinking_budget" in claude:
            cfg.thinking_budget = int(claude["thinking_budget"])

        # Hooks
        hooks_cfg = data.get("hooks", data.get("hook", {}))
        if isinstance(hooks_cfg, dict):
            for event, cmds in hooks_cfg.items():
                if isinstance(cmds, list):
                    cfg.hooks_commands[event] = [str(c) for c in cmds]
                elif isinstance(cmds, str):
                    cfg.hooks_commands[event] = [cmds]

        # hooks_dir can be under [workspace] or [hooks]
        for section in (hooks_cfg, ws):
            if isinstance(section, dict) and "hooks_dir" in section:
                d = Path(section["hooks_dir"])
                cfg.hooks_dir = d if d.is_absolute() else cfg.root_dir / d

        # Evolution
        evolution = data.get("evolution", {})
        if "enabled" in evolution:
            cfg.evolution_enabled = evolution["enabled"]
        if "worktree_base" in evolution:
            d = Path(evolution["worktree_base"])
            cfg.worktree_base = d if d.is_absolute() else cfg.root_dir / d
        if "evolve_timeout" in evolution:
            cfg.evolve_timeout = int(evolution["evolve_timeout"])
        if "meta_audit_timeout" in evolution:
            cfg.meta_audit_timeout = int(evolution["meta_audit_timeout"])
        if "max_consecutive_fails" in evolution:
            cfg.max_consecutive_fails = int(evolution["max_consecutive_fails"])

        cfg._resolve_paths(cfg.root_dir)
        return cfg

    def _resolve_paths(self, anchor: Path) -> None:
        """Ensure all path fields are absolute, resolving relative ones to *anchor*."""
        for attr_name in ("status_file", "log_dir",
                          "tech_lead_dir", "code_reviewer_dir", "security_reviewer_dir",
                          "coder_dir", "out_review_dir", "out_audit_dir", "fail_dir",
                          "task_dir",
                          "issues_file", "review_issues_file", "audit_issues_file",
                          "pilot_task_file", "summary_pack_file"):
            val: Path = getattr(self, attr_name)
            if not val.is_absolute():
                setattr(self, attr_name, anchor / val)


def load_config(path: str | Path | None = None, *, cwd: Path | None = None) -> Config:
    """Convenience wrapper around ``Config.load``."""
    return Config.load(path, cwd=cwd)


def write_default_config(path: Path) -> Path:
    """Write the bundled ``default_config.toml`` to *path*."""
    content = _DEFAULT_CONFIG_PATH.read_text()
    path.write_text(content)
    return path
