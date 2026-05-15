---
name: qcf-auto
description: "Run QCF full pipeline on a task. Usage: /qcf-auto <task.md> [--detach]"
allowed-tools: Bash, Read
---

# QCF Auto — Full Pipeline from Task

Runs the full pipeline from a task file: task-validator → tech-lead → arch-review → inner loop → commit.
Add `-c` for continuous mode (adds Pilot loop for auto-iteration).

## Usage

```
/qcf-auto <task-file>           — Validate → tech-lead → arch-review → inner loop → commit
/qcf-auto <task-file> -d        — Run in background
/qcf-auto <task-file> -c        — Continuous: +Pilot loop
```

## Execution

1. **Run** — `qcf auto <task-file> [--continuous] [--detach]`
2. **Report** — confirm result, show log location if detached
