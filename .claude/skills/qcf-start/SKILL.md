---
name: qcf-start
description: "Start QCF continuous mode. Usage: /qcf-start <task-file> [--detach]"
allowed-tools: Bash, Read
---

# QCF Start — Launch Continuous Pipeline

Starts the full Pipeline: tech-lead → implement → review → audit → pilot → repeat until STEADY_STATE.

## Usage

```
/qcf-start <task-file>             — Start continuous mode
/qcf-start <task-file> --detach    — Run in background
/qcf-start <task-file> -d          — Same, short flag
```

## Execution

1. **Validate** — check the task file exists
2. **Run** — `qcf auto <task-file> --continuous [--detach]`
3. **Report** — confirm started, show log location if detached

## Behavior

- Inner loop failures within max_rounds → normal fix rounds
- Max rounds exhausted → code reverted, fail context passed to Pilot for recovery assessment
