"""Data models used throughout the QCF."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Issue:
    """A single issue (review comment or vulnerability)."""
    file: str
    severity: str       # high / medium / low
    description: str

    @classmethod
    def from_line(cls, line: str) -> Optional["Issue"]:
        """Parse from ``file|severity|description`` format."""
        parts = line.strip().split("|", 2)
        if len(parts) == 3:
            return cls(parts[0], parts[1], parts[2])
        return None

    def to_line(self) -> str:
        return f"{self.file}|{self.severity}|{self.description}"


@dataclass
class ReviewOutput:
    result: str                     # PASS / FAIL
    summary: str
    issues: list[Issue] = field(default_factory=list)


@dataclass
class AuditOutput:
    result: str                     # PASS / FAIL
    summary: str
    vulnerabilities: list[Issue] = field(default_factory=list)


@dataclass
class StageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    timed_out: bool = False
    error: str = ""


@dataclass
class RoundStageMetric:
    """Single-stage entry in the round overview."""
    stage: str                      # implement / fix / review / audit
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
                         if e.stage in ("implement", "fix", "review", "audit")]
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
