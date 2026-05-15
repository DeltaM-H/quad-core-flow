"""Jinja2 prompt template loading and rendering (now using .md extension)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name: str, **kwargs) -> str:
    """Render a prompt template with *kwargs* as context variables.

    Templates are .md files (migrated from .j2).  Jinja2 rendering is
    still used for variable substitution.

    Available templates:
        - ``implement.md``
        - ``api_review.md``
        - ``design_review.md``
        - ``audit.md``
        - ``tech-lead.md``
        - ``pilot.md``
        - ``evolver.md``
        - ``meta_audit.md``
    """
    if not template_name.endswith(".md"):
        template_name += ".md"
    template = _env.get_template(template_name)
    return template.render(**kwargs)


def project_tree(cwd: Path | None = None, max_depth: int = 3) -> str:
    """Generate an ASCII project tree (excluding common noise)."""
    try:
        result = subprocess.run(
            ["find", ".", "-maxdepth", str(max_depth),
             "-not", "-path", "./__pycache__/*",
             "-not", "-path", "./*.egg-info/*",
             "-not", "-path", "./build/*",
             "-not", "-path", "./.git/*",
             "-not", "-path", "./node_modules/*",
             "-not", "-name", "__pycache__",
             "-not", "-name", "*.pyc",
             "-not", "-name", ".git"],
            cwd=cwd or Path.cwd(),
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout
    except Exception:
        return "(unable to generate tree)"


def implement_prompt(*, design_doc_path: str | Path,
                     issues_content: str | None = None,
                     scope_file_path: str | Path = "",
                     summary_file_path: str | Path = "",
                     brief_summary_path: str | Path = "") -> str:
    return render("implement",
                  design_doc_path=str(design_doc_path),
                  issues_content=issues_content,
                  scope_file_path=str(scope_file_path),
                  summary_file_path=str(summary_file_path),
                  brief_summary_path=str(brief_summary_path))


def api_review_prompt(*, round_num: int, summary_file_path: str | Path,
                       scope_file_path: str | Path,
                       issues_file: str | Path) -> str:
    return render("api_review",
                  round_num=round_num,
                  summary_file_path=str(summary_file_path),
                  scope_file_path=str(scope_file_path),
                  issues_file=str(issues_file))


def design_review_prompt(*, round_num: int, summary_file_path: str | Path,
                          scope_file_path: str | Path,
                          issues_file: str | Path) -> str:
    return render("design_review",
                  round_num=round_num,
                  summary_file_path=str(summary_file_path),
                  scope_file_path=str(scope_file_path),
                  issues_file=str(issues_file))


def audit_prompt(*, round_num: int, scope_file_path: str | Path,
                 summary_file_path: str | Path,
                 issues_file: str | Path) -> str:
    return render("audit",
                  round_num=round_num,
                  scope_file_path=str(scope_file_path),
                  summary_file_path=str(summary_file_path),
                  issues_file=str(issues_file))


def tech_lead_prompt(*, task_description: str, design_doc_path: str | Path,
                     project_tree_str: str = "",
                     summary_pack: str = "") -> str:
    return render("tech-lead",
                  task_description=task_description,
                  design_doc_path=str(design_doc_path),
                  project_tree=project_tree_str,
                  summary_pack=summary_pack)


def pilot_prompt(*, project_tree_str: str = "", last_task: str = "",
                  round_history: list[str] | None = None,
                  task_output_path: str | Path = "") -> str:
    return render("pilot",
                  project_tree=project_tree_str,
                  last_task=last_task,
                  round_history=round_history or [],
                  task_output_path=str(task_output_path))


def evolver_prompt(*, fail_logs: list[str], current_design: str,
                   project_tree: str = "", audit_history: str = "",
                   worktree_path: str = "") -> str:
    return render("evolver",
                  fail_logs=fail_logs,
                  current_design=current_design,
                  project_tree=project_tree,
                  audit_history=audit_history,
                  worktree_path=worktree_path)


def meta_audit_prompt(*, current_design: str, diff: str, fail_logs: str) -> str:
    return render("meta_audit",
                  current_design=current_design,
                  diff=diff,
                  fail_logs=fail_logs)
