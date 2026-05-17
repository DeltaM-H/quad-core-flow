"""Data models used throughout the QCF."""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass, field
from typing import Optional


class ActionSuggestion(str, enum.Enum):
    """REPLAN triggers evolution sandbox; RETRY continues inner loop."""
    RETRY = "RETRY"
    REPLAN = "REPLAN"

    @classmethod
    def default(cls) -> "ActionSuggestion":
        return cls.RETRY

    @classmethod
    def parse(cls, text: str) -> "ActionSuggestion":
        upper = text.strip().upper()
        if "REPLAN" in upper:
            return cls.REPLAN
        return cls.RETRY


@dataclass
class Issue:
    """A single issue (review comment or vulnerability)."""
    file: str
    severity: str       # high / medium / low
    description: str
    source: str = ""    # api / quality / security / validation

    @classmethod
    def from_line(cls, line: str) -> Optional["Issue"]:
        """Parse ``file|severity|source|description`` (4-part) or legacy ``file|severity|description`` (3-part)."""
        parts = line.strip().split("|", 3)
        if len(parts) == 4:
            return cls(file=parts[0], severity=parts[1], source=parts[2], description=parts[3])
        if len(parts) == 3:
            return cls(file=parts[0], severity=parts[1], description=parts[2])
        return None

    def to_line(self) -> str:
        if self.source:
            return f"{self.file}|{self.severity}|{self.source}|{self.description}"
        return f"{self.file}|{self.severity}|{self.description}"


@dataclass
class ReviewComponent:
    """A single perspective's review result (API or Design)."""
    perspective: str                # "api" | "design"
    result: str                     # PASS / FAIL
    issues: list[Issue] = field(default_factory=list)
    summary: str = ""


@dataclass
class ReviewOutput:
    result: str                     # PASS / FAIL
    summary: str
    issues: list[Issue] = field(default_factory=list)
    summary_feedback: str | None = None  # SUMMARY_FEEDBACK from review (if summary insufficient)
    components: list[ReviewComponent] = field(default_factory=list)


@dataclass
class AuditOutput:
    result: str                     # PASS / FAIL
    summary: str
    vulnerabilities: list[Issue] = field(default_factory=list)
    action_suggestion: str = "RETRY"  # RETRY | REPLAN


@dataclass
class TestOutput:
    """Test execution result."""
    result: str                     # PASS / FAIL
    summary: str
    failures: list[Issue] = field(default_factory=list)


@dataclass
class StageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    timed_out: bool = False
    error: str = ""


@dataclass
class RoundStageMetric:
    """Single-stage entry in the round overview."""
    stage: str                      # implement / fix / review / audit / test
    result: str                     # PASS / FAIL / TIMEOUT / SKIP / -
    input_tokens: int = 0
    output_tokens: int = 0
    summary: str = ""

    @property
    def icon(self) -> str:
        return {
            "PASS": "✓",
            "FAIL": "✗",
            "TIMEOUT": "⏱",
            "SKIP": "→",
        }.get(self.result, "–")


@dataclass
class RoundsOverview:
    """Accumulates metrics across all rounds."""
    entries: list[RoundStageMetric] = field(default_factory=list)

    def add(self, m: RoundStageMetric) -> None:
        self.entries.append(m)

    def print_round_summary(self, round_num: int, max_rounds: int) -> None:
        round_entries = [e for e in self.entries
                         if e.stage in ("implement", "fix", "review", "audit", "test")]
        tail = round_entries[-(4 if len(round_entries) >= 4 else len(round_entries)):]

        print(f"\n  ── Round {round_num:02d}/{max_rounds} 概览 ──")
        for e in tail:
            tokens = f"  {e.input_tokens:,} in / {e.output_tokens:,} out" if e.input_tokens else ""
            summary = f"  ↳ {e.summary[:100]}" if e.summary else ""
            print(f"    {e.icon} {e.stage:<12} {e.result:<8}{tokens}")
            if summary:
                print(f"       {summary}")
        print(f"  ────────────────────────────────")

    def print_final_summary(self) -> None:
        _G = "\033[32m"
        _R = "\033[31m"
        _B = "\033[1m"
        _X = "\033[0m"
        def _c(r: str, s: str) -> str:
            if r == "PASS":
                return f"{_G}{s}{_X}"
            if r in ("FAIL", "TIMEOUT"):
                return f"{_R}{s}{_X}"
            return s
        print(f"\n{_B}{'=' * 46}{_X}")
        print(f"  {_B}⚡ Quad-Core Flow 汇总{_X}")
        print(f"{_B}{'=' * 46}{_X}")
        for e in self.entries:
            print(f"  {_c(e.result, e.icon)} {e.stage}")
        print(f"{_B}{'=' * 46}{_X}")


# ── Result parsers ──

_REVIEW_PATTERN = re.compile(r"REVIEW_RESULT\s*:\s*(PASS|FAIL)", re.IGNORECASE)
_AUDIT_PATTERN = re.compile(r"AUDIT_RESULT\s*:\s*(PASS|FAIL)", re.IGNORECASE)
_TEST_PATTERN = re.compile(r"TEST_RESULT\s*:\s*(PASS|FAIL)", re.IGNORECASE)
_ACTION_SUGGESTION_PATTERN = re.compile(r"ACTION_SUGGESTION\s*:\s*(RETRY|REPLAN)", re.IGNORECASE)


def extract_review_result(text: str) -> tuple[Optional[str], str]:
    m = _REVIEW_PATTERN.search(text)
    result = m.group(1).upper() if m else None
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    summary = lines[-1] if lines else ""
    return result, summary


def extract_audit_result(text: str) -> tuple[Optional[str], str]:
    m = _AUDIT_PATTERN.search(text)
    result = m.group(1).upper() if m else None
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    summary = lines[-1] if lines else ""
    return result, summary


def extract_test_result(text: str) -> tuple[Optional[str], str]:
    m = _TEST_PATTERN.search(text)
    result = m.group(1).upper() if m else None
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    summary = lines[-1] if lines else ""
    return result, summary


@dataclass
class ScopeOutput:
    """Stage artifact: records implementation scope boundaries."""
    changed_files: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> "ScopeOutput":
        """Parse scope.json written by the implement stage."""
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text("utf-8", errors="replace"))
            return cls(
                changed_files=data.get("changed_files", []),
                dependencies=data.get("dependencies", []),
                out_of_scope=data.get("out_of_scope", []),
            )
        except (json.JSONDecodeError, Exception):
            return cls()


_SUMMARY_FEEDBACK_PATTERN = re.compile(r"SUMMARY_FEEDBACK\s*:\s*(.+)", re.IGNORECASE)


def extract_summary_feedback(text: str) -> str | None:
    """Parse SUMMARY_FEEDBACK from review output. Returns feedback text or None."""
    m = _SUMMARY_FEEDBACK_PATTERN.search(text)
    return m.group(1).strip() if m else None


def extract_action_suggestion(text: str) -> str:
    """Parse ACTION_SUGGESTION from audit output text. Returns 'RETRY' or 'REPLAN'."""
    m = _ACTION_SUGGESTION_PATTERN.search(text)
    if m:
        return m.group(1).upper()
    return "RETRY"
