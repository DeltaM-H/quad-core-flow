"""Group composition — compose atomic tasks into feature groups with contracts.

A group descriptor (``.group.md``) declares a set of atomic tasks, their
interface contracts (provides / requires), and external dependencies.  The
grouper validates that all contracts are satisfiable and produces a
dependency-ordered execution plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml  # type: ignore[import-untyped]


@dataclass
class TaskNode:
    """A single atomic task within a group."""

    file: str
    path: Path
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)


@dataclass
class GroupDef:
    """A feature group composed of multiple atomic tasks."""

    name: str
    description: str
    tasks: list[TaskNode] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    source: Path = field(default_factory=Path)

    # ── Public API ──

    def validate(self) -> list[str]:
        """Validate group contracts.

        Returns a list of error messages (empty = valid).
        """
        errors: list[str] = []
        all_provided = set(self.dependencies)  # external deps are pre-satisfied

        for task in self.tasks:
            if not task.path.exists():
                errors.append(f"Task file not found: {task.path}")

            for iface in task.provides:
                all_provided.add(iface)

        for task in self.tasks:
            for iface in task.requires:
                if iface not in all_provided:
                    errors.append(
                        f"'{task.file}' requires '{iface}' which is not provided "
                        f"by any prior task or declared as external dependency"
                    )

        # Check circular dependencies via DFS
        circular = _find_circular(self.tasks)
        if circular:
            errors.append(f"Circular dependency detected: {' → '.join(circular)}")

        return errors

    def execution_order(self) -> list[TaskNode]:
        """Return tasks topologically sorted by requires/provides.

        Falls back to file-name sort if no dependency info is declared.
        """
        if not any(t.requires for t in self.tasks):
            return sorted(self.tasks, key=lambda t: t.file)

        # Build adjacency: edge u → v means v depends on u
        provided_by: dict[str, str] = {}
        for task in self.tasks:
            for iface in task.provides:
                provided_by[iface] = task.file

        # In-degree graph
        file_index = {t.file: t for t in self.tasks}
        in_degree: dict[str, int] = {t.file: 0 for t in self.tasks}
        dep_edges: dict[str, list[str]] = {t.file: [] for t in self.tasks}

        for task in self.tasks:
            for iface in task.requires:
                provider = provided_by.get(iface)
                if provider and provider != task.file:
                    # edge: provider → task
                    dep_edges.setdefault(provider, []).append(task.file)
                    in_degree[task.file] = in_degree.get(task.file, 0) + 1

        # Kahn's algorithm
        queue = [f for f, d in in_degree.items() if d == 0]
        ordered: list[str] = []
        while queue:
            queue.sort()
            f = queue.pop(0)
            ordered.append(f)
            for dep in dep_edges.get(f, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        # Any remaining files not in ordering → append alphabetically
        remaining = [f for f in file_index if f not in ordered]
        ordered.extend(sorted(remaining))

        return [file_index[f] for f in ordered]

    # ── Factories ──

    @classmethod
    def load(cls, path: Path) -> Optional["GroupDef"]:
        """Load and parse a ``.group.md`` file with YAML frontmatter."""
        if not path.exists():
            return None
        raw = path.read_text("utf-8", errors="replace")
        return cls._parse(raw, source=path)

    @classmethod
    def _parse(cls, raw: str, *, source: Path = Path()) -> Optional["GroupDef"]:
        """Parse YAML frontmatter + body from a group descriptor string."""
        # Strip frontmatter
        fm = _parse_frontmatter(raw)
        if fm is None:
            return None

        body = _strip_frontmatter(raw)
        desc = body.strip()

        name = fm.get("name", source.stem.replace(".group", ""))
        interfaces = fm.get("interfaces") or []
        dependencies = fm.get("dependencies") or []
        raw_tasks = fm.get("tasks") or []

        tasks: list[TaskNode] = []
        task_dir = source.parent

        for entry in raw_tasks:
            if isinstance(entry, dict):
                file = entry.get("file", "")
                tasks.append(TaskNode(
                    file=file,
                    path=task_dir / file if file else source,
                    provides=entry.get("provides") or [],
                    requires=entry.get("requires") or [],
                ))

        return cls(
            name=name,
            description=desc,
            tasks=tasks,
            interfaces=interfaces,
            dependencies=dependencies,
            source=source,
        )

    def to_frontmatter_dict(self) -> dict:
        """Serialize back to a frontmatter-compatible dict."""
        return {
            "name": self.name,
            "kind": "group",
            "tasks": [
                {
                    "file": t.file,
                    "provides": t.provides,
                    "requires": t.requires,
                }
                for t in self.tasks
            ],
            "interfaces": self.interfaces,
            "dependencies": self.dependencies,
        }


# ── Helpers ──


def _parse_frontmatter(text: str) -> dict | None:
    """Extract YAML frontmatter (``--- ... ---``) from text."""
    if not text.startswith("---"):
        return None
    idx = text.find("---", 3)
    if idx == -1:
        return None
    try:
        return yaml.safe_load(text[3:idx])
    except yaml.YAMLError:
        return None


def _strip_frontmatter(text: str) -> str:
    """Strip YAML frontmatter."""
    if text.startswith("---"):
        idx = text.find("---", 3)
        if idx != -1:
            return text[idx + 3:].lstrip()
    return text


def _find_circular(tasks: list[TaskNode]) -> list[str]:
    """Detect circular dependencies between tasks.

    Returns the cycle path if found, empty list otherwise.
    """
    provided_by: dict[str, str] = {}
    for t in tasks:
        for iface in t.provides:
            provided_by[iface] = t.file

    adj: dict[str, list[str]] = {}
    for t in tasks:
        deps: list[str] = []
        for iface in t.requires:
            provider = provided_by.get(iface)
            if provider and provider != t.file:
                deps.append(provider)
        adj[t.file] = deps

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {t.file: WHITE for t in tasks}
    parent: dict[str, str | None] = {t.file: None for t in tasks}
    cycle: list[str] = []

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj.get(u, []):
            if color.get(v) == GRAY:
                # Found cycle — reconstruct
                cycle.append(v)
                cycle.append(u)
                cur = parent.get(u)
                while cur is not None and cur != v:
                    cycle.append(cur)
                    cur = parent.get(cur)
                cycle.append(v)
                cycle.reverse()
                return True
            if color.get(v) == WHITE:
                parent[v] = u
                if dfs(v):
                    return True
        color[u] = BLACK
        return False

    for t in tasks:
        if color.get(t.file) == WHITE:
            if dfs(t.file):
                return cycle
    return []


def detect_group(cfg_dir: Path, task_path: Path) -> Optional[GroupDef]:
    """Check if *task_path* belongs to a group.

    Scans for ``*.group.md`` in the same directory as *task_path* and checks
    if any of them list *task_path* as a member task.
    """
    task_dir = task_path.parent
    if not task_dir.exists():
        return None

    for group_file in sorted(task_dir.glob("*.group.md")):
        g = GroupDef.load(group_file)
        if g is None:
            continue
        # Match by task membership (split files listed in group)
        for t in g.tasks:
            if t.path.resolve() == task_path.resolve():
                return g
        # Match by base name: my-feature.md  ->  my-feature.group.md
        # (original task file that was split by the validator)
        group_base = group_file.name.replace(".group.md", "")
        if group_base == task_path.stem:
            return g
    return None


def list_groups(task_dir: Path) -> list[GroupDef]:
    """Discover all group descriptors in *task_dir*."""
    groups: list[GroupDef] = []
    if not task_dir.exists():
        return groups
    for gf in sorted(task_dir.glob("*.group.md")):
        g = GroupDef.load(gf)
        if g is not None:
            groups.append(g)
    return groups
